# Signal Research

Window: 2025-12-01 to 2026-10-31
Each baseline book buys the next open, risks one ATR, and takes profit at two ATR, with the same costs as the live book.
Universe week-close base rate: 40.9%.

Delivery's own-history z-score has a positive rank correlation with the next week.
Delivery rank correlation: 0.024.
20-day momentum rank correlation: -0.0025.

Four-session books:
- random: win rate 31.5% , expectancy -0.965%, profit factor 0.57, trades 232
- momentum_20d: win rate 39.6% , expectancy -1.115%, profit factor 0.7, trades 207
- delivery: win rate 35.7% , expectancy -0.703%, profit factor 0.68, trades 227
- pullback: win rate 33.6% , expectancy -0.6%, profit factor 0.69, trades 211
- breakout: win rate 24.6% , expectancy -0.92%, profit factor 0.41, trades 57

- random expectancy by hold: 4_sessions -0.965%, 10_sessions -1.212%, 20_sessions -1.361%
- momentum_20d expectancy by hold: 4_sessions -1.115%, 10_sessions -1.137%, 20_sessions -0.839%
- delivery expectancy by hold: 4_sessions -0.703%, 10_sessions -1.116%, 20_sessions -0.945%
- pullback expectancy by hold: 4_sessions -0.6%, 10_sessions -0.708%, 20_sessions -0.686%
- breakout expectancy by hold: 4_sessions -0.92%, 10_sessions -1.109%, 20_sessions -1.229%
