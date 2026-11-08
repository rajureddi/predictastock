# Signal Research

Window: 2026-05-08 to 2026-11-07
Each baseline book buys the next open, risks one ATR, and takes profit at two ATR, with the same costs as the live book.
Universe week-close base rate: 41.4%.

Delivery's own-history z-score has a positive rank correlation with the next week.
Delivery rank correlation: 0.0371.
20-day momentum rank correlation: -0.0452.

Four-session books:
- random: win rate 31.2% , expectancy -1.315%, profit factor 0.41, trades 128
- momentum_20d: win rate 37.3% , expectancy -1.335%, profit factor 0.63, trades 110
- delivery: win rate 36.3% , expectancy -0.25%, profit factor 0.88, trades 124
- pullback: win rate 36.2% , expectancy -0.493%, profit factor 0.76, trades 127
- breakout: win rate 25.6% , expectancy -0.896%, profit factor 0.44, trades 43

- random expectancy by hold: 4_sessions -1.315%, 10_sessions -1.475%, 20_sessions -1.146%
- momentum_20d expectancy by hold: 4_sessions -1.335%, 10_sessions -1.86%, 20_sessions -1.746%
- delivery expectancy by hold: 4_sessions -0.25%, 10_sessions -0.876%, 20_sessions -0.825%
- pullback expectancy by hold: 4_sessions -0.493%, 10_sessions -0.805%, 20_sessions -0.642%
- breakout expectancy by hold: 4_sessions -0.896%, 10_sessions -1.32%, 20_sessions -1.492%
