# Weekly Engine Backtest

Window: 2026-10-01 to 2026-10-29 (custom)
Generated: 2026-11-05T23:16:44
Cadence: signal on the Monday close, fill at the next open, exit at the stop, the target, or the last close through Saturday.
Universe: 1211 names, the same full-market screen as the live desk.

- Win rate: 20.0%
- Universe base rate: 28.1%
- Excess hit rate: -8.1 points
- Expectancy: -2.397% per filled trade
- Profit factor: 0.2
- Hits: 3
- Losses: 12
- Rejected fills: 0
- Data errors removed: 0
- Average up: +3.05%
- Average down: -3.76%
- Portfolio: -3.42% on ₹1000000.0, max drawdown 3.42%
- Win-rate interval (week bootstrap): None% to None%

Next phase: HOLD
Hold. 15 filled trades is below the 100 needed. Win rate so far is 20.0%.

Same filled signals, held longer:
- week: win rate 20.0% on 15 trades, expectancy -2.397
- 10_sessions: win rate 20.0% on 15 trades, expectancy -2.095
- 20_sessions: win rate 20.0% on 5 trades, expectancy -1.63

Baseline books over the same weeks (4-session hold, same costs):
- random: win rate 31.5%, expectancy -0.965%, profit factor 0.57, trades 232
- momentum_20d: win rate 39.6%, expectancy -1.115%, profit factor 0.7, trades 207
- delivery: win rate 35.7%, expectancy -0.703%, profit factor 0.68, trades 227
- pullback: win rate 33.6%, expectancy -0.6%, profit factor 0.69, trades 211
- breakout: win rate 24.6%, expectancy -0.92%, profit factor 0.41, trades 57
