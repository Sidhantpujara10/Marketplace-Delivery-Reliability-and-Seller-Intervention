# Findings and Recommendations

**Scope:** 94,819 delivered orders from 2,924 sellers, purchased January 2017 to August 2018.
**Source:** Olist public dataset. Queries are in `sql/`, statistics in `pipeline/03_analyse.py`.

## Summary

Late delivery on this marketplace is mainly a carrier and lane problem, not a seller problem. Seller late rates do not persist, so punitive action would target noise. Two things do persist: a small group of sellers who miss dispatch deadlines, and 12 lanes. The recommendation is a bounded test on those two, starting with the lanes.

## 1. Scorecard

| KPI | Value |
|---|---|
| Late order rate | 6.86% (95% interval 6.7 to 7.02) |
| Late orders | 6,506 |
| Excess days on late orders | 69,096 in total; median 8, 90th percentile 23, 95th percentile 32 |
| Dispatch time | median 1.85 days, 90th percentile 6.0 |
| Transit time | median 7.1 days, 90th percentile 19.0 |
| Dispatch deadline missed | 9.03% of orders |
| Value tied to late orders | R$ 1,146,291 (7.56% of order value) |

Late orders are costly in reputation: 62.4% receive 1 or 2 stars, against 9.2% of on time orders.

## 2. Dispatch or transit?

| Cause | Late orders | Share | Average excess days |
|---|---|---|---|
| Transit: seller on time, carrier late | 4,695 | 72.2% | 10.9 |
| Dispatch: seller missed the handover deadline | 1,811 | 27.8% | 9.8 |

## 3. Did the mix change, or did performance?

Three months spiked: November 2017, February 2018 and March 2018. Late rate went from 4.53% in the other months to 15.16%, a rise of 10.64 points. A Kitagawa decomposition splits that rise:

| Dimension | From a different mix | From the same mix performing worse |
|---|---|---|
| Category | 0.03 points | 10.6 points |
| Lane | 0.17 points | 10.47 points |
| Seller | 0.76 points | 9.88 points |

Mix explains at most 7% of the rise. By cause, 8.73 of the 10.64 points were transit and 1.9 were dispatch. The spikes were a capacity problem in the carrier network around Black Friday and early 2018.

## 4. Is delay concentrated in a few sellers or lanes?

**Sellers: less than it looks.** The top 5% of sellers by late orders (146 sellers) hold 58.5% of late orders (95% interval 57.29 to 59.75). The same sellers ship 49.56% of all orders. They are over-represented by about 9 points, not 53.

**Lanes: yes.** São Paulo to Rio de Janeiro alone is 8,044 orders with a 14.3% late rate and 17.7% of all late orders, 79% of them transit caused. São Paulo to Bahia, Espírito Santo and Ceará run at 12% to 14%.

## 5. Which sellers deserve attention?

A naive rule (late rate above the platform, 30 or more orders) flags 83 sellers. Adjusting for the month and destination of each seller's orders clears 32 of them, leaving 64. Below the minimum volume, 224 sellers show a late rate of 25% or more on a handful of orders and are not judged.

Then the test that matters. Flags set on data to February 2018, judged on April to August 2018:

| Flag | Sellers | Before: flagged / others | After: flagged / others | Gap that persisted |
|---|---|---|---|---|
| Late rate, naive | 45 | 12.89% / 5.68% | 3.76% / 4.63% | none |
| Late rate, adjusted for mix | 39 | 13.57% / 5.84% | 4.04% / 4.58% | none |
| Dispatch deadline missed | 87 | 26.99% / 6.27% | 13.11% / 7.11% | 29% |
| Lanes, late rate | 12 lanes | 12.98% / 4.84% | 6.36% / 4.12% | 28% |

Sellers flagged on late rate were slightly better than everyone else afterwards. Their earlier results reflected when and where they shipped, plus chance. Missed dispatch deadlines are different: it is the one measure a seller controls, and the flagged group still missed deadlines almost twice as often.

**Cohorts.** Sellers who joined in the first half of 2018 run a little worse (5.2% late, 8.8% deadline missed) than 2017 cohorts (4.1% to 4.4%, 7.2%) over the same months. In their first 30 days sellers miss the dispatch deadline on 10.2% of orders against 8.9% later. Onboarding is a reasonable place for deadline guidance.

## 6. What would an intervention buy?

**Seller dispatch coaching.** 120 sellers are flagged on dispatch across the full period, with 882 dispatch caused late orders in 20 months. Simulating 5,000 runs with sampling noise, 29% persistence and a coaching effect drawn from 15% to 50%:

| | Late orders avoided per year |
|---|---|
| 10th percentile | 18 |
| Median | 45 |
| 90th percentile | 92 |

That is small. In the break-even workbook, a pilot of 30 sellers pays for itself only if it costs under about R$ 40 per seller at a R$ 40 cost per late order. Account manager time will not clear that bar; automated deadline reminders might.

**Longer promise on the 12 persistent lanes.** These lanes held 26.2% of late orders in the holdout months. Adding days to the estimate there would have turned this many late orders into on time ones over five months:

| Days added | 1 | 2 | 3 | 4 | 5 | 7 |
|---|---|---|---|---|---|---|
| Late orders avoided | 41 | 73 | 106 | 134 | 159 | 211 |

Three days removes 106 of 368 late orders (29%), about 254 a year. The promise on these lanes already averages 29.0 days, so the risk is lost orders from a longer quote. The workbook shows this still pays as long as each added day loses fewer than about 1.2% of orders on those lanes, at the placeholder costs.

## Recommendations

1. **Do not penalise sellers on late rate.** The data shows it does not identify sellers who will be late in future.
2. **Run a lane test first.** A/B test a promise three days longer on São Paulo to Rio de Janeiro and the other persistent lanes. Measure late rate, review scores and conversion. Raise transit performance on those lanes with the carrier.
3. **Run a small, cheap dispatch pilot.** Start with the 30 flagged sellers with the most dispatch caused late orders. Use automated deadline reminders and a handover cut off review. Frame it as support. Its purpose is to measure the coaching effect, which nobody knows yet.
4. **Plan carrier capacity for peaks.** November, February and March drove the worst months, and it was transit, not sellers.
5. **Add dispatch deadline guidance to onboarding.** New sellers miss more deadlines in their first 30 days.

## Limitations

Costs in the workbook are placeholders. The coaching effect is assumed, not measured. The promise analysis assumes delivery times stay the same. The dataset is a sample, so absolute counts are small. See the README for the full list.
