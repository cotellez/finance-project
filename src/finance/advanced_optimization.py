"""Advanced portfolio optimization models.

Implements three alpha-enhancing, estimation-error-robust approaches:
  1. Hierarchical Risk Parity (HRP) - clustering-based allocation that avoids
     covariance-matrix inversion instability of classic MPT.
  2. Black-Litterman - blends market-equilibrium returns with investor views.
  3. Kelly Criterion - maximizes long-run geometric growth via edge/odds sizing.

These complement the existing Modern Portfolio Theory optimizer in
``optimization.py``.
"""

import numpy as np
import pandas as pd
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform


def _cov_to_corr(cov: pd.DataFrame) -> pd.DataFrame:
    d = np.sqrt(np.diag(cov.values))
    d = np.where(d == 0, 1.0, d)
    corr = (cov.values / np.outer(d, d)).clip(-1.0, 1.0)
    # Ensure exact symmetry (numerical noise can break linkage).
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    return pd.DataFrame(corr, index=cov.index, columns=cov.columns)


def _quasi_diag(link: np.ndarray) -> list:
    """Sort clustered items by distance to recover quasi-diagonal covariance."""
    link = link.astype(int)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    num_items = link[-1, 3]
    while sort_ix.max() >= num_items:
        sort_ix = sort_ix.reset_index(drop=True)
        found = False
        for i in range(sort_ix.shape[0]):
            val = sort_ix[i]
            if val >= num_items:
                cluster_index = val - num_items
                new_vals = pd.Series(link[cluster_index, 0:2])
                head = sort_ix.iloc[:i]
                tail = sort_ix.iloc[i + 1:]
                sort_ix = pd.concat([head, new_vals, tail], ignore_index=True)
                found = True
                break
        if not found:
            break
    sort_ix = sort_ix.iloc[::-1]
    return sort_ix.tolist()


def _get_cluster_var(cov: pd.DataFrame, cluster_items: list) -> float:
    """Variance of a portfolio that is inverse-variance weighted within a cluster."""
    if len(cluster_items) == 0:
        return 0.0
    if len(cluster_items) == 1:
        return max(float(cov.loc[cluster_items[0], cluster_items[0]]), 1e-9)
    cluster_cov = cov.loc[cluster_items, cluster_items].values
    # Jitter the diagonal to keep near-singular covariance matrices invertible.
    eps = 1e-10
    cluster_cov = cluster_cov + eps * np.eye(len(cluster_items))
    try:
        inv = np.linalg.inv(cluster_cov)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(cluster_cov)
    inv_sum = inv.sum()
    if inv_sum == 0 or not np.isfinite(inv_sum):
        w = np.ones(len(cluster_items)) / len(cluster_items)
    else:
        w = inv.sum(axis=1) / inv_sum
    w = w.reshape(-1, 1)
    var_val = np.dot(np.dot(w.T, cluster_cov), w)
    var = float(np.asarray(var_val).reshape(-1)[0])
    if not np.isfinite(var) or var <= 0:
        var = 1e-9
    return var


def _recursive_bisect(cov: pd.DataFrame, items: list, weights: list) -> None:
    """Recursively split a cluster and accumulate risk-based weights.

    `weights` is a parallel list aligned with `items`; each slot accumulates a
    multiplier as the tree is descended (canonical HRP bisection).
    """
    if len(items) == 1:
        return

    left = items[: len(items) // 2]
    right = items[len(items) // 2:]
    left_idx = list(range(len(left)))
    right_idx = list(range(len(left), len(items)))

    left_var = _get_cluster_var(cov, left)
    right_var = _get_cluster_var(cov, right)
    inv_left = 1.0 / left_var
    inv_right = 1.0 / right_var
    alpha_left = inv_left / (inv_left + inv_right)

    for i in left_idx:
        weights[i] *= alpha_left
    for i in right_idx:
        weights[i] *= (1.0 - alpha_left)

    _recursive_bisect(cov, left, weights[: len(left)])
    _recursive_bisect(cov, right, weights[len(left):])


def hierarchical_risk_parity(price_df: pd.DataFrame) -> dict:
    """Compute weights using Hierarchical Risk Parity (HRP).

    Args:
        price_df: DataFrame of adjusted-close prices, columns = tickers.

    Returns:
        dict with tickers, weights, and a brief description.
    """
    if price_df.empty or len(price_df.columns) < 2:
        raise ValueError("HRP requires at least two assets.")

    price_df = price_df.dropna(axis=1, how="any")
    tickers = list(price_df.columns)
    returns = np.log(price_df / price_df.shift(1)).dropna()
    cov = returns.cov()

    corr = _cov_to_corr(cov)
    dist = np.sqrt(np.clip((1 - corr) / 2, 0, 1))
    condensed = squareform(dist.values)

    link = hierarchy.linkage(condensed, method="single")
    sort_ix = _quasi_diag(link)
    sorted_tickers = [tickers[int(i)] for i in sort_ix]

    weights_list = [1.0] * len(sorted_tickers)
    _recursive_bisect(cov, sorted_tickers, weights_list)
    total = sum(weights_list)
    if total <= 0 or not np.isfinite(total):
        weights_list = [1.0 / len(sorted_tickers)] * len(sorted_tickers)
    weights = {t: float(w) / sum(weights_list) for t, w in zip(sorted_tickers, weights_list)}

    weight_dict = {t.upper(): round(float(weights[t]), 4) for t in sorted_tickers}

    return {
        "method": "hierarchical_risk_parity",
        "tickers": [t.upper() for t in sorted_tickers],
        "weights": weight_dict,
        "note": "HRP uses correlation-clustering and inverse-variance allocation, robust to covariance-matrix instability.",
    }


def black_litterman(
    price_df: pd.DataFrame,
    market_weights: dict | None = None,
    views: dict | None = None,
    view_confidence: float = 0.5,
    risk_free_rate: float = 0.04,
) -> dict:
    """Black-Litterman model blending market equilibrium with investor views.

    Args:
        price_df: DataFrame of adjusted-close prices, columns = tickers.
        market_weights: Prior market-cap weights per ticker (default: equal).
        views: Dict mapping ticker -> expected excess return view (e.g., {"AAPL": 0.12}).
        view_confidence: How strongly views are trusted (0..1).
        risk_free_rate: Annualized risk-free rate (default 4%).

    Returns:
        dict with blended weights, implied returns, and view-adjusted returns.
    """
    if price_df.empty or len(price_df.columns) < 1:
        raise ValueError("Black-Litterman requires at least one asset.")

    price_df = price_df.dropna(axis=1, how="any")
    tickers = list(price_df.columns)
    n = len(tickers)

    returns = np.log(price_df / price_df.shift(1)).dropna()
    mean_returns = returns.mean() * 252
    cov = returns.cov() * 252

    if market_weights is None:
        w_mkt = pd.Series(1.0 / n, index=tickers)
    else:
        w_mkt = pd.Series({t: market_weights.get(t, 0.0) for t in tickers}, index=tickers)
        w_mkt = w_mkt / w_mkt.sum()

    # Implied equilibrium excess returns via reverse optimization.
    # pi = delta * cov * w_mkt  (delta = risk aversion; approximated by Sharpe of mkt).
    market_portfolio_var = float(np.dot(w_mkt.values.T, np.dot(cov.values, w_mkt.values)))
    delta = (float(np.dot(w_mkt.values.T, mean_returns.values)) - risk_free_rate) / market_portfolio_var if market_portfolio_var > 0 else 1.0
    pi = delta * np.dot(cov.values, w_mkt.values)
    pi = pd.Series(pi, index=tickers)

    # Build views matrix (P) and view variance.
    if views:
        view_tickers = list(views.keys())
        P = np.zeros((len(view_tickers), n))
        for i, t in enumerate(view_tickers):
            P[i, tickers.index(t)] = 1.0
        q = np.array([views[t] for t in view_tickers])
        tau = 1.0 / (len(returns) * 0.1 + 1)
        omega = np.diag(np.diag(np.dot(P, np.dot(tau * cov.values, P.T)))) * (1.0 / max(view_confidence, 1e-6))
    else:
        P = np.zeros((0, n))
        q = np.array([])
        tau = 1.0 / (len(returns) * 0.1 + 1)
        omega = np.zeros((0, 0))

    # Posterior mean (Black-Litterman closed form when P non-empty).
    if P.shape[0] > 0:
        pi_arr = pi.values.reshape(-1, 1)
        m1 = np.linalg.inv(np.linalg.inv(tau * cov.values) + np.dot(P.T, np.dot(np.linalg.inv(omega), P)))
        m2 = np.dot(np.linalg.inv(tau * cov.values), pi_arr) + np.dot(P.T, np.dot(np.linalg.inv(omega), q.reshape(-1, 1)))
        posterior = np.dot(m1, m2).ravel()
    else:
        posterior = pi.values

    posterior = pd.Series(posterior, index=tickers)

    # Constrained weights maximizing Sharpe given posterior returns.
    from scipy.optimize import minimize

    def neg_sharpe(w):
        ret = float(np.dot(posterior.values, w))
        vol = float(np.sqrt(np.dot(w.T, np.dot(cov.values, w))))
        return -(ret - risk_free_rate) / vol if vol > 0 else 0.0

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = tuple((0.0, 1.0) for _ in range(n))
    init = np.array([1.0 / n] * n)

    result = minimize(neg_sharpe, init, method="SLSQP", bounds=bounds, constraints=constraints)
    if not result.success:
        raise RuntimeError(f"Black-Litterman optimization failed: {result.message}")

    weight_dict = {t.upper(): round(float(w), 4) for t, w in zip(tickers, result.x)}

    return {
        "method": "black_litterman",
        "tickers": [t.upper() for t in tickers],
        "weights": weight_dict,
        "implied_equilibrium_returns": {t: round(float(v), 4) for t, v in pi.items()},
        "view_adjusted_returns": {t: round(float(v), 4) for t, v in posterior.items()},
    }


def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> dict:
    """Compute optimal Kelly fraction for long-term geometric growth.

    Args:
        win_rate: Probability of a winning trade (0..1).
        avg_win: Average gain per winning trade (as decimal, e.g., 0.10 = 10%).
        avg_loss: Average loss per losing trade (as positive decimal).

    Returns:
        dict with full Kelly fraction, fractional (conservative) Kelly, and notes.
    """
    if not 0 < win_rate < 1:
        raise ValueError("win_rate must be strictly between 0 and 1.")
    if avg_win <= 0 or avg_loss <= 0:
        raise ValueError("avg_win and avg_loss must be positive decimals.")

    b = avg_win / avg_loss
    f_star = (win_rate * b - (1 - win_rate)) / b

    return {
        "win_rate": win_rate,
        "avg_win_pct": avg_win * 100,
        "avg_loss_pct": avg_loss * 100,
        "full_kelly_fraction": round(float(f_star), 4),
        "half_kelly_fraction": round(float(f_star * 0.5), 4),
        "quarter_kelly_fraction": round(float(f_star * 0.25), 4),
        "note": (
            "Full Kelly maximizes geometric growth but is aggressive; fractional "
            "Kelly (half/quarter) reduces variance while retaining most of the "
            "growth." if f_star > 0 else
            "Negative Kelly indicates the edge does not justify betting; do not size "
            "positions in this setup."
        ),
    }
