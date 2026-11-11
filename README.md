# Ladder

A dashboard that applies a fixed buy-the-dip, take-profit ladder to each of your holdings and tells you which ones need a trade. It runs entirely on GitHub: a scheduled workflow fetches closing prices, and GitHub Pages serves the page.

## The rules

| Change since purchase | What to do |
| --- | --- |
| Down 10% | Hold |
| Down 20% | Add 10% |
| Down 30% | Add 20% |
| Down 40% | Add 30% |
| Down 50% | Add 50% |
| Up 10% or 20% | Hold |
| Up 30% | Sell 10% |
| Up 40% | Sell 20% |
| Up 50% | Sell 30% |
| Up 60% | Sell 40% |
| Up 100% | Sell everything |

How the page applies them:

- Change is measured from the price you paid. If you give only a purchase date, it uses that day's closing price (or the last trading day before it).
- Between two rungs, the nearer one already passed applies. Up 45% follows the up-40% rule; down 70% follows the down-50% rule.
- Each percentage is a share of what you hold in that position at the time.
- A rung counts once. After you make the trade, press **Mark done**; the rung then stays quiet even if the price leaves and comes back. Marking a rung done also covers the smaller rungs before it. If you listed a share count, marking a rung done adjusts it for you.
- If the price jumps past several rungs before you act, only the furthest one is shown.

To change the thresholds or percentages, edit `strategy.json`.

## Set up (about ten minutes)

1. **Create a repository.** Go to <https://github.com/new>, name it `ladder`, and create it with no README. See the privacy note below before choosing a name.
2. **Upload these files.** On the new repository's page choose "uploading an existing file". Open the unzipped folder on your computer and make hidden files visible (Mac: `Cmd+Shift+.`; Windows shows them already) so the `.github` folder appears. Select everything *inside* the folder, including `.github`, drag it onto the page, and commit.
3. **Turn on Pages.** Settings → Pages → under "Build and deployment", set Source to **GitHub Actions**.
4. **Run it once.** Actions tab → "Update dashboard" → "Run workflow". (The run that started when you uploaded will have failed at its last step because Pages wasn't on yet. That's expected.)
5. **Open the dashboard** at `https://YOUR-USERNAME.github.io/ladder/`.

If you use git on the command line instead of step 2: `git init -b main`, `git add -A`, `git commit -m "Ladder"`, add the remote, and push.

## Using it

- **Add a holding** with the form at the bottom of the page. Give a purchase date, the price you paid, or both, and optionally the number of shares.
- **Mark done**, **Undo** and **Remove** are on each holding.

All of these open a pre-filled GitHub issue. Submit the issue; the workflow applies it, closes the issue with a reply, and republishes the page in about a minute. Only issues from you (or collaborators you invite) are acted on.

You can also edit `holdings.csv` directly on GitHub:

```
ticker,purchase_date,shares,purchase_price,done
VOO,2025-03-03,12.5,,
NVDA,,172.5,42.10,+30
```

`purchase_date` is YYYY-MM-DD. `shares` and `purchase_price` are optional, but a row needs a date or a price. `done` lists finished rungs separated by semicolons, such as `-20;-30`. One row per ticker and purchase date.

For a position built over several purchases, either enter each purchase as its own row, or enter one row with your average cost as the price and no date.

Prices refresh on weekdays after the US close and again later in the evening for mutual funds. To refresh sooner, run the workflow by hand from the Actions tab.

## Things to know

- **Privacy.** A GitHub Pages site is readable by anyone who has its address, and on a free GitHub plan the repository must be public too. Your tickers, purchase prices and share counts would be visible. Leave `shares` blank to keep position sizes out of it; the page then shows percentages only.
- **Price source.** Prices come from Yahoo Finance through the `yfinance` library. It is free and unofficial, so it can fail now and then. When it does, the page keeps the last good prices and says so, and it warns you if prices are more than a few days old.
- **Ticker spelling** follows Yahoo: `BRK-B`, `BTC-USD`, `VFIAX`.
- **Splits.** Prices are split-adjusted. If a stock has split since you bought it, enter the split-adjusted price and today's share count.
- **Price or total return.** The page measures price change by default. The "Price plus dividends" switch counts dividends and fund distributions as well, which matters for funds that pay large distributions. It needs a purchase date.
- **Closing prices only.** Signals use the latest daily close, not intraday prices.
