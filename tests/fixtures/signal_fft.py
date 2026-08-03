"""科学计算样本代码：生成一个含噪音正弦信号 + FFT 结果，等待可视化补全。"""

import numpy as np


def generate_signal(duration: float = 1.0, sample_rate: int = 1024,
                    freqs: tuple = (5.0, 12.0, 30.0), noise_level: float = 0.3) -> np.ndarray:
    """生成一个多频叠加的信号。

    Args:
        duration: 信号时长（秒）
        sample_rate: 采样率（Hz）
        freqs: 叠加频率成分（Hz）
        noise_level: 高斯噪声幅度
    Returns:
        长度 duration*sample_rate 的 ndarray
    """
    t = np.linspace(0, duration, int(duration * sample_rate), endpoint=False)
    signal = np.zeros_like(t)
    for f in freqs:
        signal += np.sin(2 * np.pi * f * t)
    noise = np.random.default_rng(42).normal(0, noise_level, size=t.shape)
    return signal + noise


def compute_fft(signal: np.ndarray, sample_rate: int = 1024) -> tuple:
    """计算幅度谱。返回 (freqs, magnitudes)。"""
    n = len(signal)
    freqs = np.fft.rfftfreq(n, d=1.0 / sample_rate)
    magnitudes = np.abs(np.fft.rfft(signal))
    return freqs, magnitudes


# 顶层变量：待可视化的数据
sample_rate = 1024
signal = generate_signal(duration=2.0, sample_rate=sample_rate)
fft_freqs, fft_magnitudes = compute_fft(signal, sample_rate=sample_rate)

print(f"signal 形状: {signal.shape}, dtype: {signal.dtype}")
print(f"FFT 频率范围: {fft_freqs[0]:.2f} ~ {fft_freqs[-1]:.2f} Hz")
