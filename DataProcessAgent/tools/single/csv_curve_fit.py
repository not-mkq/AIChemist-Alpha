# tools/single/csv_curve_fit.py
import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
import sympy
import re

from tool_runtime import (
    regist_tool,
    return_json,
    return_file,
)

def csv_curve_fit(
    tool_name: str,
    input_file: str,
    x_column: str,
    y_column: str,
    formula: str,
    output_y_column: str = "fitted_y",
    initial_guesses: str = "",  # 格式如 "a=1, b=0.5"
) -> None:
    """
    通用非线性曲线拟合工具。
    - 自动识别公式中的参数（除 x 以外的字母）。
    - 支持常用函数：lg, ln, exp, sqrt, sin, cos, tan, abs, pi, e。
    - 计算参数值、标准差、R2 和 RMSE。
    - 将拟合曲线存入新列以便绘图对比。
    """
    file_path = input_file
    df = pd.read_csv(file_path)

    # 1. 预处理公式和变量
    # 替换常见的数学函数，使其符合 sympy 语法（如 lg -> log10）
    processed_formula = formula.replace("lg", "log10").replace("ln", "log")
    
    # 提取所有字母变量名
    all_symbols = sorted(list(set(re.findall(r'[a-zA-Z_]\w*', processed_formula))))
    
    # 排除已知的数学函数名和保留变量 x
    math_funcs = {'exp', 'sqrt', 'sin', 'cos', 'tan', 'log', 'log10', 'pi', 'abs'}
    params_names = [s for s in all_symbols if s != 'x' and s not in math_funcs]
    
    if not params_names:
        raise ValueError(f"No fitting parameters found in formula. Symbols detected: {all_symbols}")

    # 2. 构建计算函数
    # 使用 sympy 定义符号
    x_sym = sympy.Symbol('x')
    p_syms = [sympy.Symbol(name) for name in params_names]
    
    # 解析表达式
    try:
        expr = sympy.parse_expr(processed_formula)
    except Exception as e:
        raise ValueError(f"Failed to parse formula '{formula}': {e}")
        
    # 将表达式转换为高性能的 numpy 函数
    # 函数签名要求：f(x, p1, p2, ...)
    model_func = sympy.lambdify([x_sym] + p_syms, expr, 'numpy')

    # 3. 准备数据
    # 剔除空值
    valid_data = df[[x_column, y_column]].dropna()
    X_data = valid_data[x_column].values
    Y_data = valid_data[y_column].values

    # 解析初值
    p0 = None
    if initial_guesses:
        guess_dict = {}
        for part in initial_guesses.split(','):
            if '=' in part:
                k, v = part.split('=')
                guess_dict[k.strip()] = float(v.strip())
        p0 = [guess_dict.get(name, 1.0) for name in params_names]
    else:
        p0 = [1.0] * len(params_names)

    # 4. 执行拟合
    try:
        popt, pcov = curve_fit(model_func, X_data, Y_data, p0=p0, maxfev=5000)
    except Exception as e:
        raise RuntimeError(f"Fitting failed: {e}")

    # 5. 计算评价指标
    # 拟合值
    Y_fit_valid = model_func(X_data, *popt)
    
    # R2
    ss_res = np.sum((Y_data - Y_fit_valid) ** 2)
    ss_tot = np.sum((Y_data - np.mean(Y_data)) ** 2)
    r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    # RMSE
    rmse = np.sqrt(np.mean((Y_data - Y_fit_valid) ** 2))
    
    # 参数标准差 (Standard Errors)
    perr = np.sqrt(np.diag(pcov))

    # 6. 保存结果到 CSV
    # 计算全表的拟合值（包含原本是空行的地方，如果 x 有值的话）
    df[output_y_column] = model_func(df[x_column].values, *popt)
    df.to_csv(file_path, index=False)
    
    # 将修改后的文件交还给系统
    return_file(file_path)

    # 7. 返回指标 JSON
    result = {
        "r2": float(r2),
        "rmse": float(rmse),
    }
    # 添加各个参数及其误差
    for i, name in enumerate(params_names):
        result[name] = float(popt[i])
        result[f"{name}_err"] = float(perr[i])

    return_json(result)

# 注册工具
regist_tool(csv_curve_fit, tool_name="csv_curve_fit")
