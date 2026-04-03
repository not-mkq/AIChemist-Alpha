# -*- coding: utf-8 -*-
"""
:File: utils.py
:Author: zhoudl@mail.ustc.edu.cn
"""
import inspect
import os
import time
from itertools import product
from typing import Optional, Sequence, Type

import joblib
import numpy as np
import scipy
import torch
from joblib import Parallel, delayed
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, StackDataset
from tqdm import tqdm


DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def get_grid(num: int = 5, min_pct: int = 5, max_pct: int = 35, step: int = 1) -> np.ndarray:
    return np.array([pcts for pcts in product(range(min_pct, max_pct + 1, step), repeat=num) if sum(pcts) == 100]) / 100


def expected_improvement(mean: np.ndarray, std: np.ndarray, y_max: float, xi: float = 0.) -> np.ndarray:
    a = mean - y_max - xi
    z = a / std
    return a * scipy.stats.norm.cdf(z) + std * scipy.stats.norm.pdf(z)


# https://doi.org/10.48550/arXiv.1505.08052
def get_penalization(L_const: float, x: np.ndarray, mean: np.ndarray, std: np.ndarray, x0: np.ndarray) -> np.ndarray:
    M_const = mean.max()
    z = (L_const * np.sqrt(((x - x0) ** 2).sum(axis=-1)) - M_const + mean) / (np.sqrt(2) * std)
    return 1 / 2 * scipy.special.erfc(-z)


def get_L_const(x: np.ndarray, y: np.ndarray, start: int, end: int) -> float:
    end = min(end, len(x))
    L_const = []
    for i in range(start, end):
        dis_x = np.sqrt(((x - x[i]) ** 2).sum(axis=-1))
        dis_x[i] = np.inf
        dis_y = np.abs(y - y[i])
        L_const.append((dis_y / dis_x).max())
    return max(L_const)


class Callback:
    def __init__(self, optimizer: torch.optim.Optimizer, factor: float = 0.5, patience: int = 10,
                 threshold: float = 1e-4, min_lr: float = 1e-6):
        self.optimizer = optimizer
        self.factor = factor
        self.patience = patience
        self.threshold = threshold
        self.min_lr = min_lr
        self.best = torch.inf
        self.num_bad_epochs = 0

    def step(self, current: float):
        if current < self.best * (1. - self.threshold):
            self.best = current
            self.num_bad_epochs = 0
        else:
            self.num_bad_epochs += 1
            if self.num_bad_epochs > self.patience:
                for param_group in self.optimizer.param_groups:
                    param_group['lr'] = float(param_group['lr']) * self.factor
                self.num_bad_epochs = 0
                if max([float(group['lr']) for group in self.optimizer.param_groups]) < self.min_lr:
                    return False
        return True


class TheoreticalModel(torch.nn.Module):
    def __init__(self, depth: int = 4, hidden_size: int = 1024, input_size: int = 5, output_size: int = 5):
        super().__init__()
        assert depth > 0
        if depth == 1:
            layers = [torch.nn.Linear(input_size, output_size)]
        else:
            layers = ([torch.nn.Linear(input_size, hidden_size), torch.nn.ReLU()]
                      + [torch.nn.Linear(hidden_size, hidden_size), torch.nn.ReLU()] * (depth - 2)
                      + [torch.nn.Linear(hidden_size, output_size)])
        self.seq = torch.nn.Sequential(*layers)

    def forward(self, x: torch.Tensor):
        return self.seq(x)


class ExperimentalModel(torch.nn.Module):
    def __init__(self, submodel: torch.nn.Module, depth: int = 3, hidden_size: int = 64, dropout: float = 0.25,
                 input_size: int = 5, output_size: int = 1):
        super().__init__()
        assert depth > 0
        assert 0. <= dropout < 1.
        self.submodel = submodel
        for param in self.submodel.parameters():
            param.requires_grad = False

        if depth == 1:
            layers = [torch.nn.Linear(input_size + self.submodel.seq[-1].out_features, output_size)]
        else:
            layers = ([torch.nn.Linear(input_size + self.submodel.seq[-1].out_features, hidden_size),
                       torch.nn.ReLU(), torch.nn.Dropout(dropout)]
                      + [torch.nn.Linear(hidden_size, hidden_size), torch.nn.ReLU(), torch.nn.Dropout(dropout)]
                      * (depth - 2)
                      + [torch.nn.Linear(hidden_size, output_size)])
        self.seq = torch.nn.Sequential(*layers)

    def forward(self, x: torch.Tensor):
        x = torch.cat((x, self.submodel(x)), dim=1)
        return self.seq(x)


def train_model(
        model_class: Type[torch.nn.Module],
        train_loader: DataLoader,
        val_loader: Optional[DataLoader] = None,
        lr: float = 1e-3,
        max_epochs: int = 1000,
        **kwargs
) -> torch.nn.Module:
    model_kwargs = {key: value for key, value in kwargs.items() if key in inspect.signature(model_class).parameters}
    callback_kwargs = {key: value for key, value in kwargs.items() if key in inspect.signature(Callback).parameters}
    model = model_class(**model_kwargs).to(DEVICE)
    loss_func = torch.nn.L1Loss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = Callback(optimizer, **callback_kwargs)
    progress_bar = tqdm(range(max_epochs), desc='Training', unit='epoch')

    for epoch in progress_bar:
        start = time.time()
        model.train()
        train_samples = 0
        train_loss = 0.
        for step, (x, y) in enumerate(train_loader):
            loss = loss_func(model(x), y)
            loss.backward()
            train_samples += x.shape[0]
            train_loss += loss.item() * x.shape[0]
            optimizer.step()
            optimizer.zero_grad()
        metrics = {'train_loss': f'{train_loss / train_samples:.4f}'}

        if val_loader is not None:
            model.eval()
            val_samples = 0
            val_loss = 0.
            for x, y in val_loader:
                loss = loss_func(model(x), y)
                val_samples += x.shape[0]
                val_loss += loss.item() * x.shape[0]
            metrics['val_loss'] = f'{val_loss / val_samples:.4f}'

        metrics['lr'] = f'{optimizer.param_groups[0]["lr"]:.3e}'
        metrics['time'] = f'{time.time() - start:.4f}s'
        progress_bar.set_postfix(metrics)

        if not scheduler.step(train_loss):
            progress_bar.total = epoch
            break

    return model


def theo_exp_pipeline(
        iteration: int,
        experimental_data: Sequence[np.ndarray],
        theoretical_data: Optional[Sequence[np.ndarray]] = None,
        model_saved_dir: Optional[str] = None
) -> tuple[dict[int, torch.nn.Module], dict[int, StandardScaler]]:
    assert iteration >= 0 and len(experimental_data) == 2
    model_saved_dir = '.' if model_saved_dir is None else model_saved_dir
    paths_theo = [path for path in os.listdir(model_saved_dir) if path.startswith('theoretical')]

    if len(paths_theo) == 0:
        assert iteration == 0 and theoretical_data is not None and len(theoretical_data) == 2
        x_train_theo, y_train_theo = theoretical_data
        norm_theo = StandardScaler().fit(y_train_theo)
        y_train_theo_norm = norm_theo.transform(y_train_theo)
        train_data_theo = StackDataset(
            torch.tensor(x_train_theo, device=DEVICE, dtype=torch.float32),
            torch.tensor(y_train_theo_norm, device=DEVICE, dtype=torch.float32),
        )
        train_loader_theo = DataLoader(train_data_theo, batch_size=256, shuffle=True)
        theoretical_model = train_model(TheoreticalModel, train_loader_theo)
        save_path_theo = f'{model_saved_dir}/theoretical_{time.strftime("%Y%m%d_%H%M%S")}'
        os.makedirs(save_path_theo)
        torch.save(theoretical_model, f'{save_path_theo}/model.pth')
        joblib.dump(norm_theo, f'{save_path_theo}/norm.pkl')
        print(f'Theoretical model saved to: {save_path_theo}')
    else:
        load_path_theo = f'{model_saved_dir}/{sorted(paths_theo)[-1]}'
        theoretical_model = torch.load(
            f'{load_path_theo}/model.pth', weights_only=False, map_location=DEVICE
        ).to(DEVICE)
        print(f'Theoretical model loaded from: {load_path_theo}')

    x_exp, y_exp = experimental_data
    batch_size_exp = round(x_exp.shape[0] / 40)
    experimental_models, norms_exp = {}, {}
    for i, (train_idx_exp, _) in enumerate(KFold(n_splits=10, shuffle=True, random_state=6).split(x_exp)):
        x_train_exp, y_train_exp = x_exp[train_idx_exp], y_exp[train_idx_exp]
        norm_exp = StandardScaler().fit(y_train_exp)
        y_train_exp_norm = norm_exp.transform(y_train_exp)
        train_data_exp = StackDataset(
            torch.tensor(x_train_exp, device=DEVICE, dtype=torch.float32),
            torch.tensor(y_train_exp_norm, device=DEVICE, dtype=torch.float32),
        )
        train_loader_exp = DataLoader(train_data_exp, batch_size=batch_size_exp, shuffle=True)
        experimental_model = train_model(ExperimentalModel, train_loader_exp, submodel=theoretical_model,
                                         patience=int(np.sqrt(1e5 / len(x_train_exp))))
        experimental_models[i] = experimental_model
        norms_exp[i] = norm_exp
        save_path_exp = f'{model_saved_dir}/experimental_{iteration}_{i}_{time.strftime("%Y%m%d_%H%M%S")}'
        os.makedirs(save_path_exp)
        torch.save(experimental_model, f'{save_path_exp}/model.pth')
        joblib.dump(norm_exp, f'{save_path_exp}/norm.pkl')
        print(f'Experimental model saved to: {save_path_exp}')
    return experimental_models, norms_exp


def bayesian_optimization(
        data: Sequence[np.ndarray],
        iteration: Optional[int] = None,
        model_saved_dir: Optional[str] = None,
        models: Optional[dict[int, torch.nn.Module]] = None,
        norms: Optional[dict[int, StandardScaler]] = None,
        grid_step: int = 5,
        n_jobs: int = -1,
        num_select: int = 20
) -> Optional[np.ndarray]:
    assert (iteration is not None and model_saved_dir is not None) or (models is not None and norms is not None)
    if models is None or norms is None:
        models, norms = {}, {}
        for i in range(10):
            paths = [path for path in os.listdir(model_saved_dir) if path.startswith(f'experimental_{iteration}_{i}')]
            assert len(paths) > 0
            load_path = f'{model_saved_dir}/{sorted(paths)[-1]}'
            models[i] = torch.load(
                f'{load_path}/model.pth', weights_only=False, map_location=DEVICE
            ).to(DEVICE)
            norms[i] = joblib.load(f'{load_path}/norm.pkl')

    x, y = data
    grid = get_grid(step=grid_step)
    y_preds, grid_preds = [], []
    for i in range(10):
        models[i].eval()
        with torch.no_grad():
            y_preds.append(
                norms[i].inverse_transform(
                    models[i](torch.tensor(x, device=DEVICE, dtype=torch.float32)).cpu().numpy()
                ).ravel()
            )
            grid_preds.append(
                norms[i].inverse_transform(
                    models[i](torch.tensor(grid, device=DEVICE, dtype=torch.float32)).cpu().numpy()
                ).ravel()
            )
    y_preds = np.sort(np.array(y_preds).T, axis=1)[:, 1:-1].mean(axis=1)
    grid_preds = np.sort(np.array(grid_preds).T, axis=1)[:, 1:-1]  # remove the maximum and minimum values

    norm = StandardScaler().fit(y)
    y_preds_n = norm.transform(y_preds[:, None]).ravel()
    grid_preds_n = norm.transform(grid_preds.ravel()[:, None]).reshape(-1, 8)
    mean_n = grid_preds_n.mean(axis=1)
    std_n = grid_preds_n.std(ddof=1, axis=1)

    ei = expected_improvement(-mean_n, std_n, -y_preds_n.min())
    batch_size = 1024
    L_const = max(Parallel(n_jobs=n_jobs, verbose=100)(
        delayed(get_L_const)(grid, -mean_n, i * batch_size, (i + 1) * batch_size)
        for i in range((grid.shape[0] - 1) // batch_size + 1)))

    selected = []
    ei_t = ei.copy()
    while len(selected) < num_select:
        best = ei_t.argmax()
        ei_t[best] = -np.inf
        if (np.sqrt(((grid[selected] - grid[best]) ** 2).sum(axis=-1)) <= 0.02).any():
            continue
        selected.append(best)
        ei_t *= get_penalization(L_const, grid, -mean_n, std_n, grid[best])
    selected = np.array(selected)
    if grid_step > 1 and (grid[selected, None] == x).all(axis=-1).any(axis=-1).sum() >= 8:
        return

    selected = []
    ei_t = ei.copy()
    ei_t[(grid[:, None] == x).all(axis=-1).any(axis=-1)] = -np.inf
    while len(selected) < num_select:
        best = ei_t.argmax()
        ei_t[best] = -np.inf
        if (np.sqrt(((grid[selected] - grid[best]) ** 2).sum(axis=-1)) <= 0.02).any():
            continue
        selected.append(best)
        ei_t *= get_penalization(L_const, grid, -mean_n, std_n, grid[best])
    selected = np.array(selected)
    return grid[selected]
