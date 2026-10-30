# repopilot-demo-polyglot

Four tiny projects in four languages, each with **one deliberate bug**. It exists so you can try
[RepoPilot AI](https://github.com/Xdiad47/RepoPilot-AI) on code that is not Python.

> The tests are **expected to fail** on `main`. Please don't "fix" them here; fork the repository to experiment.

| Folder | Stack | Symptom a user would report |
| --- | --- | --- |
| `go-cart/` | Go | A 10% discount takes off 100% of the price |
| `flutter-app/` | Flutter / Dart | Page 1 of the product list skips the first items and the last page is empty |
| `kotlin-service/` | Kotlin / Gradle | A profile with no ratings yet shows `NaN` instead of `0.0` |
| `web/` | TypeScript / Vitest | Prices are missing their thousands separators: 1234.5 shows as `1234.50` |

Run the tests locally with each ecosystem's own tool (`go test ./...`, `flutter test`, `./gradlew test`, `npm test`).
