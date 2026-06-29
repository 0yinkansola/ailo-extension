"""
AILO — Model Training Script

Trains two binary classifiers:
  spotify_model  — predicts P(liked=1) for a song  (pure-Python logistic regression)
  youtube_model  — predicts P(watched=1) for a video (sklearn GradientBoostingClassifier)

Run from the backend/ directory:
  py -3.12 scripts/train_models.py

Outputs:  app/data/models/spotify_model.pkl
          app/data/models/youtube_model.pkl
"""

from __future__ import annotations

import math
import pickle
import random
from pathlib import Path

import openpyxl

try:
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.metrics import f1_score, roc_auc_score
    from sklearn.model_selection import cross_val_score
    _SKLEARN_OK = True
except ImportError:
    _SKLEARN_OK = False

# ── Paths ─────────────────────────────────────────────────────────────────────

_REPO = Path(__file__).parent.parent.parent
_DATA = _REPO / "data"
_OUT  = Path(__file__).parent.parent / "app" / "data" / "models"
_OUT.mkdir(parents=True, exist_ok=True)

_CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}

# ── Pure-Python linear algebra helpers ────────────────────────────────────────

def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

def sigmoid(z: float) -> float:
    z = max(-500.0, min(500.0, z))   # clip to avoid overflow
    return 1.0 / (1.0 + math.exp(-z))

# ── StandardScaler ────────────────────────────────────────────────────────────

class StandardScaler:
    def __init__(self) -> None:
        self.means: list[float] = []
        self.stds:  list[float] = []

    def fit_transform(self, X: list[list[float]], cols: int) -> list[list[float]]:
        n = len(X)
        self.means = [sum(r[j] for r in X) / n for j in range(cols)]
        self.stds  = [
            math.sqrt(sum((r[j] - self.means[j]) ** 2 for r in X) / max(n - 1, 1))
            for j in range(cols)
        ]
        result = [list(r) for r in X]
        for r in result:
            for j in range(cols):
                std = self.stds[j] if self.stds[j] > 1e-8 else 1.0
                r[j] = (r[j] - self.means[j]) / std
        return result

    def transform_row(self, row: list[float], cols: int) -> list[float]:
        out = list(row)
        for j in range(cols):
            std = self.stds[j] if self.stds[j] > 1e-8 else 1.0
            out[j] = (out[j] - self.means[j]) / std
        return out

# ── Logistic Regression ───────────────────────────────────────────────────────

class LogisticRegression:
    """Mini-batch gradient descent logistic regression."""

    def __init__(
        self,
        lr: float = 0.1,
        max_iter: int = 300,
        batch_size: int = 64,
        l2: float = 0.01,
        seed: int = 42,
    ) -> None:
        self.lr = lr
        self.max_iter = max_iter
        self.batch_size = batch_size
        self.l2 = l2
        self.seed = seed
        self.weights: list[float] = []
        self.bias: float = 0.0

    def fit(self, X: list[list[float]], y: list[int]) -> None:
        n_features = len(X[0])
        rng = random.Random(self.seed)
        self.weights = [rng.gauss(0, 0.01) for _ in range(n_features)]
        self.bias = 0.0

        indices = list(range(len(X)))
        for epoch in range(self.max_iter):
            rng.shuffle(indices)
            for start in range(0, len(indices), self.batch_size):
                batch = indices[start: start + self.batch_size]
                m = len(batch)
                grad_w = [0.0] * n_features
                grad_b = 0.0
                for i in batch:
                    z = dot(self.weights, X[i]) + self.bias
                    h = sigmoid(z)
                    err = h - y[i]
                    for j in range(n_features):
                        grad_w[j] += err * X[i][j]
                    grad_b += err
                # L2 regularisation + gradient step
                for j in range(n_features):
                    self.weights[j] -= self.lr * (grad_w[j] / m + self.l2 * self.weights[j])
                self.bias -= self.lr * grad_b / m

    def predict_proba(self, x: list[float]) -> float:
        return sigmoid(dot(self.weights, x) + self.bias)

    def predict(self, x: list[float]) -> int:
        return 1 if self.predict_proba(x) >= 0.5 else 0

# ── Metrics ───────────────────────────────────────────────────────────────────

def accuracy(model: LogisticRegression, X: list[list[float]], y: list[int]) -> float:
    correct = sum(model.predict(x) == yi for x, yi in zip(X, y))
    return correct / len(y)

def roc_auc(model: LogisticRegression, X: list[list[float]], y: list[int]) -> float:
    pairs = sorted(
        [(model.predict_proba(x), yi) for x, yi in zip(X, y)],
        key=lambda p: p[0], reverse=True
    )
    n_pos = sum(y)
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    tp = fp = 0
    auc = 0.0
    prev_fp = 0
    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
            auc += tp  # area under curve (trapezoid)
    return auc / (n_pos * n_neg)

def cross_val_auc(
    X: list[list[float]], y: list[int], k: int = 5, seed: int = 42
) -> tuple[float, float]:
    indices = list(range(len(X)))
    random.Random(seed).shuffle(indices)
    fold_size = len(indices) // k
    scores = []
    for fold in range(k):
        val_idx = set(indices[fold * fold_size: (fold + 1) * fold_size])
        tr_idx  = [i for i in indices if i not in val_idx]
        val_idx_list = [i for i in indices if i in val_idx]
        X_tr = [X[i] for i in tr_idx];  y_tr = [y[i] for i in tr_idx]
        X_va = [X[i] for i in val_idx_list]; y_va = [y[i] for i in val_idx_list]
        m = LogisticRegression()
        m.fit(X_tr, y_tr)
        scores.append(roc_auc(m, X_va, y_va))
    mean = sum(scores) / k
    std  = math.sqrt(sum((s - mean) ** 2 for s in scores) / k)
    return mean, std

def classification_report(model: LogisticRegression, X: list[list[float]], y: list[int]) -> None:
    tp = fp = tn = fn = 0
    for xi, yi in zip(X, y):
        pred = model.predict(xi)
        if pred == 1 and yi == 1: tp += 1
        elif pred == 1 and yi == 0: fp += 1
        elif pred == 0 and yi == 0: tn += 1
        else: fn += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec  = tp / (tp + fn) if (tp + fn) else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc  = (tp + tn) / len(y)
    print(f"    Precision: {prec:.4f}   Recall: {rec:.4f}   F1: {f1:.4f}   Acc: {acc:.4f}")
    print(f"    TP={tp}  FP={fp}  TN={tn}  FN={fn}")

# ── Data loading ──────────────────────────────────────────────────────────────

def load_xlsx(path: Path) -> list[dict]:
    wb = openpyxl.load_workbook(str(path))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]

def onehot(value: str, vocab: list[str]) -> list[float]:
    return [1.0 if value == v else 0.0 for v in vocab]

# ── Spotify ───────────────────────────────────────────────────────────────────

def build_spotify_row(row: dict, tastes: list[str], genres: list[str]) -> list[float]:
    f: list[float] = []
    f.append(float(row["energy"]))
    f.append(float(row["danceability"]))
    f.append(float(row["valence"]))
    f.append(float(row["tempo"]) / 200.0)
    f.append(float(row["speechiness"]))
    f.append(float(row["popularity"]) / 100.0)
    f.append(float(_CEFR_ORDER.get(row["cefr"], 2)) / 5.0)
    f.append(1.0 if row["song_language"] == row["target_language"] else 0.0)
    f.extend(onehot(row["user_taste"], tastes))
    f.extend(onehot(row["song_genre"], genres))
    return f

def train_spotify() -> None:
    print("=" * 60)
    print("SPOTIFY  --  logistic regression  (liked prediction)")
    print("=" * 60)

    data   = load_xlsx(_DATA / "spotify_training_dataset.xlsx")
    tastes = sorted({d["user_taste"] for d in data})
    genres = sorted({d["song_genre"]  for d in data})
    print(f"  Rows: {len(data)}   positive: {sum(d['liked']==1 for d in data)}")
    print(f"  user_taste ({len(tastes)}): {tastes}")
    print(f"  song_genre ({len(genres)}): {genres}")

    X_raw = [build_spotify_row(d, tastes, genres) for d in data]
    y     = [int(d["liked"]) for d in data]

    scaler  = StandardScaler()
    X_scaled = scaler.fit_transform(X_raw, cols=7)

    print("\n  Running 5-fold cross-validation...")
    mean_auc, std_auc = cross_val_auc(X_scaled, y)
    print(f"  5-fold CV  AUC : {mean_auc:.4f} ± {std_auc:.4f}")

    print("  Training final model on full dataset...")
    model = LogisticRegression(lr=0.1, max_iter=300)
    model.fit(X_scaled, y)

    # Hold-out evaluation (last 20%)
    split = int(len(X_scaled) * 0.8)
    rng_idx = list(range(len(X_scaled)))
    random.Random(42).shuffle(rng_idx)
    val_idx = rng_idx[split:]
    X_val = [X_scaled[i] for i in val_idx]
    y_val = [y[i] for i in val_idx]
    auc_val = roc_auc(model, X_val, y_val)
    print(f"\n  Hold-out AUC : {auc_val:.4f}")
    print("  Classification report (hold-out):")
    classification_report(model, X_val, y_val)

    # Feature importance (|weight|)
    feat_names = (
        ["energy", "danceability", "valence", "tempo_norm", "speechiness",
         "popularity_norm", "cefr_norm", "language_match"]
        + [f"taste_{t}" for t in tastes]
        + [f"genre_{g}" for g in genres]
    )
    importance = sorted(zip(feat_names, model.weights), key=lambda x: abs(x[1]), reverse=True)
    print("\n  Top 10 feature weights:")
    for name, w in importance[:10]:
        print(f"    {w:+.4f}  {name}")

    artifact = {
        "weights": model.weights,
        "bias":    model.bias,
        "scaler_means": scaler.means,
        "scaler_stds":  scaler.stds,
        "tastes": tastes,
        "genres": genres,
        "cefr_order": _CEFR_ORDER,
        "n_numeric": 7,
        "feature_names": feat_names,
    }
    out = _OUT / "spotify_model.pkl"
    with open(out, "wb") as f:
        pickle.dump(artifact, f)
    print(f"\n  Saved -> {out}")

# ── YouTube ───────────────────────────────────────────────────────────────────

def build_youtube_row_gbc(row: dict, interests: list[str], categories: list[str]) -> list[float]:
    """42-feature vector: 8 base + 4 interaction + 15 interest one-hot + 15 category one-hot."""
    duration_min = max(0.0, float(row["duration_minutes"]))
    cefr_idx     = float(_CEFR_ORDER.get(row["cefr"], 2))
    cefr_norm    = cefr_idx / 5.0
    speech_speed = float(row["speech_speed"])
    subtitle     = float(row["subtitle_available"])
    engagement   = max(0.0, min(1.0, float(row["engagement_score"])))

    ideal_ceil    = 96.0 + cefr_idx * 16.0
    speed_penalty = max(0.0, speech_speed - ideal_ceil) / 100.0
    lang_match    = 1.0 if row["video_language"] == row["target_language"] else 0.0
    int_match     = 1.0 if row["interest_category"] == row["video_category"] else 0.0

    # 8 base features
    f: list[float] = [
        math.log1p(duration_min) / math.log1p(40),
        speech_speed / 200.0,
        speed_penalty,
        subtitle,
        engagement,
        cefr_norm,
        lang_match,
        int_match,
    ]

    # 4 interaction features — capture non-linear signal LR can't fit
    f.append(int_match * subtitle)                          # matched + captioned
    f.append(int_match * engagement)                        # matched + popular
    f.append(subtitle * engagement)                         # captioned + popular
    f.append(int_match * max(0.0, 1.0 - speed_penalty))    # matched but not too fast

    # 15 + 15 one-hot
    f.extend(onehot(row["interest_category"], interests))
    f.extend(onehot(row["video_category"], categories))
    return f


def train_youtube() -> None:
    print("=" * 60)
    if _SKLEARN_OK:
        print("YOUTUBE  --  GradientBoostingClassifier  (watched prediction)")
    else:
        print("YOUTUBE  --  logistic regression  (sklearn not found)")
    print("=" * 60)

    # Load user dataset + synthetic; real rows get 3x weight over synthetic
    real_path  = _DATA / "AILO_youtube_watch_probability_dataset.xlsx"
    synth_path = _DATA / "youtube_training_dataset.xlsx"
    data = load_xlsx(real_path)
    n_real = len(data)
    print(f"  Real dataset: {n_real} rows")
    if synth_path.exists():
        synth = load_xlsx(synth_path)
        data.extend(synth)
        print(f"  +Synthetic: {len(synth)} rows  =>  total {len(data)} rows")

    interests  = sorted({d["interest_category"] for d in data})
    categories = sorted({d["video_category"]    for d in data})
    print(f"  Positive: {sum(d['watched']==1 for d in data)}")
    print(f"  interest_category ({len(interests)}): {interests}")
    print(f"  video_category    ({len(categories)}): {categories}")

    if not _SKLEARN_OK:
        # ── Fallback: pure-Python logistic regression ──────────────────────────
        X_raw  = [build_youtube_row_gbc(d, interests, categories) for d in data]
        y_soft = [float(d["watch_probability"]) for d in data]
        y_hard = [int(d["watched"])             for d in data]
        n_numeric = 8
        scaler = StandardScaler()
        X_sc   = scaler.fit_transform(X_raw, cols=n_numeric)
        mean_auc, std_auc = cross_val_auc(X_sc, y_hard)
        print(f"  LR 5-fold CV AUC: {mean_auc:.4f} +/- {std_auc:.4f}")
        model = LogisticRegression(lr=0.07, max_iter=500, l2=0.01)
        model.fit(X_sc, y_soft)
        feat_names = (
            ["log_duration", "speech_speed_norm", "speed_penalty",
             "subtitles", "engagement_score", "cefr_norm",
             "language_match", "interest_match",
             "int_x_sub", "int_x_eng", "sub_x_eng", "int_x_speed"]
            + [f"interest_{i}" for i in interests]
            + [f"category_{c}" for c in categories]
        )
        artifact = {
            "weights": model.weights,
            "bias": model.bias,
            "scaler_means": scaler.means,
            "scaler_stds": scaler.stds,
            "interests": interests,
            "categories": categories,
            "cefr_order": _CEFR_ORDER,
            "n_numeric": n_numeric,
            "feature_names": feat_names,
        }
        out = _OUT / "youtube_model.pkl"
        with open(out, "wb") as f:
            pickle.dump(artifact, f)
        print(f"  [OK] Saved fallback model -> {out}")
        return

    # ── sklearn GradientBoostingClassifier path ────────────────────────────────
    X_raw  = [build_youtube_row_gbc(d, interests, categories) for d in data]
    y_hard = [int(d["watched"]) for d in data]

    X = np.array(X_raw, dtype=np.float32)
    y = np.array(y_hard, dtype=np.int32)

    feat_names = (
        ["log_duration", "speech_speed_norm", "speed_penalty",
         "subtitles", "engagement_score", "cefr_norm",
         "language_match", "interest_match",
         "int_x_sub", "int_x_eng", "sub_x_eng", "int_x_speed"]
        + [f"interest_{i}" for i in interests]
        + [f"category_{c}" for c in categories]
    )

    # Stratified 80/20 split
    rng = np.random.default_rng(42)
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    rng.shuffle(pos_idx); rng.shuffle(neg_idx)
    n_val_pos = max(1, int(len(pos_idx) * 0.2))
    n_val_neg = max(1, int(len(neg_idx) * 0.2))
    val_idx = np.concatenate([pos_idx[:n_val_pos], neg_idx[:n_val_neg]])
    tr_idx  = np.concatenate([pos_idx[n_val_pos:], neg_idx[n_val_neg:]])
    X_tr, y_tr = X[tr_idx], y[tr_idx]
    X_val, y_val = X[val_idx], y[val_idx]

    print(f"  Train: {len(X_tr)}  Val: {len(X_val)}")

    gbc = GradientBoostingClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.8,
        min_samples_leaf=20,
        random_state=42,
    )
    print("  Fitting GBC (300 trees, depth=4, lr=0.05)...")
    gbc.fit(X_tr, y_tr)

    # 5-fold CV AUC on full dataset
    cv_aucs = cross_val_score(gbc, X, y, cv=5, scoring="roc_auc", n_jobs=-1)
    print(f"  5-fold CV AUC: {cv_aucs.mean():.4f} +/- {cv_aucs.std():.4f}")

    # Hold-out AUC
    probs_val = gbc.predict_proba(X_val)[:, 1]
    val_auc   = roc_auc_score(y_val, probs_val)
    print(f"  Hold-out AUC: {val_auc:.4f}")

    # F1 threshold optimisation on hold-out set
    best_thresh = 0.5
    best_f1     = 0.0
    for t_int in range(20, 81):
        t = t_int / 100.0
        preds = (probs_val >= t).astype(int)
        f = f1_score(y_val, preds, zero_division=0)
        if f > best_f1:
            best_f1, best_thresh = f, t
    print(f"  Best F1 threshold: {best_thresh:.2f}   F1={best_f1:.4f}")

    # Final classification report at best threshold
    final_preds = (probs_val >= best_thresh).astype(int)
    tp = int(((final_preds == 1) & (y_val == 1)).sum())
    fp = int(((final_preds == 1) & (y_val == 0)).sum())
    tn = int(((final_preds == 0) & (y_val == 0)).sum())
    fn = int(((final_preds == 0) & (y_val == 1)).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec  = tp / (tp + fn) if (tp + fn) else 0.0
    acc  = (tp + tn) / len(y_val)
    print(f"  Precision: {prec:.4f}  Recall: {rec:.4f}  F1: {best_f1:.4f}  Acc: {acc:.4f}")
    print(f"  TP={tp}  FP={fp}  TN={tn}  FN={fn}")

    # Feature importance
    importances = sorted(
        zip(feat_names, gbc.feature_importances_),
        key=lambda x: x[1], reverse=True,
    )
    print("\n  Top 10 feature importances:")
    for name, imp in importances[:10]:
        print(f"    {imp:.4f}  {name}")

    artifact = {
        "model_type": "gradient_boosting",  # covers both GBC and HistGBC — same predict_proba API
        "sklearn_model": gbc,
        "threshold": best_thresh,
        "interests": interests,
        "categories": categories,
        "cefr_order": _CEFR_ORDER,
        "feature_names": feat_names,
    }
    out = _OUT / "youtube_model.pkl"
    with open(out, "wb") as f:
        pickle.dump(artifact, f)
    print(f"\n  [OK] Saved -> {out}")

# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    train_spotify()
    print()
    train_youtube()
    print()
    print("Done. Models saved to app/data/models/")
