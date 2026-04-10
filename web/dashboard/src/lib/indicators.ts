/**
 * Client-side technical indicator calculations.
 * All functions return arrays aligned to the input data length.
 * Values before enough data is available are returned as null.
 */

/** Simple Moving Average */
export function sma(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  if (period <= 0 || period > data.length) return result;

  let sum = 0;
  for (let i = 0; i < period - 1; i++) {
    sum += data[i];
  }
  for (let i = period - 1; i < data.length; i++) {
    sum += data[i];
    result[i] = sum / period;
    sum -= data[i - period + 1];
  }
  return result;
}

/** Exponential Moving Average */
export function ema(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  if (period <= 0 || data.length < period) return result;

  const k = 2 / (period + 1);

  // Seed with SMA of first `period` values
  let sum = 0;
  for (let i = 0; i < period; i++) {
    sum += data[i];
  }
  let prev = sum / period;
  result[period - 1] = prev;

  for (let i = period; i < data.length; i++) {
    prev = data[i] * k + prev * (1 - k);
    result[i] = prev;
  }
  return result;
}

export interface BollingerBands {
  upper: (number | null)[];
  middle: (number | null)[];
  lower: (number | null)[];
}

/** Bollinger Bands (SMA ± stdDev * σ) */
export function bollingerBands(
  data: number[],
  period: number,
  stdDevMultiplier: number
): BollingerBands {
  const middle = sma(data, period);
  const upper: (number | null)[] = new Array(data.length).fill(null);
  const lower: (number | null)[] = new Array(data.length).fill(null);

  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const avg = middle[i] as number;
    const variance =
      slice.reduce((acc, v) => acc + (v - avg) ** 2, 0) / period;
    const sigma = Math.sqrt(variance);
    upper[i] = avg + stdDevMultiplier * sigma;
    lower[i] = avg - stdDevMultiplier * sigma;
  }

  return { upper, middle, lower };
}

/** Standard deviation over a rolling window */
export function stdDev(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null);
  const means = sma(data, period);
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1);
    const avg = means[i] as number;
    const variance = slice.reduce((acc, v) => acc + (v - avg) ** 2, 0) / period;
    result[i] = Math.sqrt(variance);
  }
  return result;
}
