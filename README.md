# Big Dreams Small Steps

**You tell us the big dream. We give you one small step a day. All you say is yes or no.**

There's a simple truth behind most big accomplishments: people get there by taking small, consistent steps and keeping a promise to themselves. Big Dreams Small Steps turns that truth into a daily habit.

## The idea

You set one big, audacious goal — *"own a self-sustaining farm in Ethiopia that creates local jobs,"* *"start a company,"* *"become fluent in another language."* The kind of goal that feels like a series of impossible leaps.

Every day, the app gives you **one small task** that moves you toward it. You answer one question: **did you do it — yes or no?**

That's the whole friction floor. One decision a day. Over time, the small wins compound, your understanding of the problem deepens, and the leap becomes a staircase.

### How it works

1. **Set your dream.** Describe your big goal in your own words.
2. **Get today's step.** The app breaks the goal into a credible next action — research, a skill to practice, a person to reach out to, a concept to learn.
3. **Answer yes or no.** Keep your promise to yourself and build the streak.
4. **Go further if you want.** Feeling motivated? Knock out extra steps and get ahead. But the only requirement is one step a day.
5. **Adapt and pivot.** Goals change. Move the farm from Ethiopia to America, narrow the focus, or change direction entirely — the path adjusts with you.

The aim isn't just to check boxes. It's to build real understanding — of the domain, the supply chains, the regulations, the fundamentals — so that by the time you reach the goal, you actually know how to sustain it.

## Why it works

The approach is grounded in well-studied behavioral research:

- **Tiny habits** — small actions anchored to a clear identity beat willpower and motivation over the long run.
- **The progress principle** — small, visible wins are one of the strongest drivers of sustained motivation.
- **Streaks and commitment** — keeping a promise to yourself, day after day, is what turns intention into identity.

## Principles

- **One step a day.** The bar to participate is always low enough to clear.
- **Learning over speculation.** Steps focus on research, skills, relationships, and understanding — not financial advice or "buy this asset" calls.
- **Honest about the path.** We don't promise to plan ten years of a complex, cross-border goal. We promise a credible *next* step and a path that adapts as you go.
- **Built to survive the slip.** Missing a day isn't failure. The point is to come back tomorrow.

## Status

Early stage, but there's a working MVP. It runs as a zero-build static site
(plain HTML/CSS/JS) with progress saved in your browser via `localStorage` —
no backend or API keys required yet.

### Run it

Open `index.html` directly in a browser, or serve the folder:

```bash
npx http-server -p 8137
# then visit http://127.0.0.1:8137
```

Set a big dream, get today's small step, answer yes or no, and watch your
streak grow. "Go further" gives you another step the same day; "Edit or pivot"
changes the goal.

The app is mobile-first: installable to your home screen (PWA), works fully
offline, and every control is sized for thumbs. On a phone, open the site and
use "Add to Home Screen" to get the standalone app experience.

### Project layout

```
index.html            # views: onboarding + daily step
styles.css            # styling (mobile-first, safe-area aware)
js/tasks.js           # step generator (stubbed; seam for the Claude API)
js/store.js           # localStorage persistence
js/app.js             # UI controller + service worker registration
manifest.webmanifest  # PWA manifest (installable, standalone)
sw.js                 # service worker: precaches the app shell for offline
icons/                # app icon (SVG + PNG renditions incl. maskable)
```

The step generator in `js/tasks.js` is currently an offline heuristic. It is
written so it can be swapped for a Claude API call (`claude-opus-4-8`) that
takes your goal plus history and returns the next step, without changing the
rest of the app.

## Roadmap

- [x] Landing page that explains the idea and captures the first goal
- [x] Daily task view with a one-tap yes / no
- [x] Streak tracking and history
- [x] Saved progress (currently in-browser via `localStorage`)
- [x] Mobile-friendly: installable PWA, offline support, thumb-sized touch targets
- [ ] Export / import progress as a backup (guards against browser storage eviction)
- [ ] AI-generated next step from your goal and progress (replace the stub)
- [ ] Weekly reflection on how far you've come
- [ ] Accounts and synced progress across devices
- [ ] Subscription ($10/mo concept under exploration)

## License

TBD
