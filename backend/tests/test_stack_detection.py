"""Language-agnostic understanding: frameworks, dependencies, test commands, stack-trace frames and outlines."""

import pytest

from app.core.security import protected_reason
from app.services.repository_analyzer import RepositoryAnalyzer
from app.services.repository_service import RepositoryService
from app.services.stack_detector import detect_stack


def index_of(settings, root, files: dict[str, str]):
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return RepositoryService(settings).index(root)


def profile_of(settings, tmp_path, files):
    return RepositoryAnalyzer().profile(index_of(settings, tmp_path, files))


class TestFrameworkDetection:
    def test_flutter_app(self, settings, tmp_path):
        p = profile_of(settings, tmp_path, {
            "pubspec.yaml": "name: shop\ndependencies:\n  flutter:\n    sdk: flutter\n  provider: ^6.0.0\n  dio: ^5.0.0\ndev_dependencies:\n  flutter_test:\n    sdk: flutter\n",
            "lib/main.dart": "void main() {}\n", "lib/login.dart": "class Login {}\n", "test/login_test.dart": "void main() {}\n",
            "android/app/build.gradle": "apply plugin: 'com.android.application'\n", "ios/Runner/AppDelegate.swift": "import UIKit\n",
        })
        assert p.primary_language == "Dart" and p.supported
        assert {"Flutter", "Provider", "Dio", "Android"} <= set(p.frameworks)
        assert "flutter test" in p.test_commands and "flutter_test" in p.test_frameworks
        assert "pubspec.yaml" in p.manifests

    def test_android_kotlin_app(self, settings, tmp_path):
        p = profile_of(settings, tmp_path, {
            "app/build.gradle.kts": 'plugins { id("com.android.application") }\ndependencies {\n  implementation("androidx.compose.ui:ui:1.6")\n  testImplementation("junit:junit:4.13")\n}\n',
            "app/src/main/AndroidManifest.xml": "<manifest/>\n", "gradlew": "#!/bin/sh\n",
            "app/src/main/java/App.kt": "class App\n", "app/src/main/java/Home.kt": "class Home\n",
        })
        assert p.primary_language == "Kotlin"
        assert {"Android", "Jetpack Compose", "Gradle"} <= set(p.frameworks)
        assert any(c.endswith("./gradlew test") for c in p.test_commands)
        assert "JUnit" in p.test_frameworks

    def test_swiftui_ios_app(self, settings, tmp_path):
        p = profile_of(settings, tmp_path, {
            "App/ContentView.swift": "import SwiftUI\nstruct ContentView: View {}\n", "App/Model.swift": "import Combine\n",
            "App.xcodeproj/project.pbxproj": "IPHONEOS_DEPLOYMENT_TARGET = 17.0;\n", "Tests/AppTests.swift": "import XCTest\n",
        })
        assert p.primary_language == "Swift"
        assert {"SwiftUI", "Combine", "Xcode", "iOS"} <= set(p.frameworks)
        assert "XCTest" in p.test_frameworks and p.test_commands and p.test_commands[0].startswith("xcodebuild test")

    def test_nextjs_typescript(self, settings, tmp_path):
        p = profile_of(settings, tmp_path, {
            "package.json": '{"dependencies": {"next": "16", "react": "19"}, "devDependencies": {"vitest": "5", "tailwindcss": "4"}, "scripts": {"test": "vitest run"}}',
            "app/page.tsx": "export default function Page() {}\n", "lib/x.ts": "export const x = 1\n",
        })
        assert p.primary_language == "TypeScript"
        assert {"Next.js", "React", "Tailwind CSS"} <= set(p.frameworks)
        assert p.test_commands == ["npm test"] and "vitest" in p.test_frameworks

    def test_monorepo_commands_name_their_directory(self, settings, tmp_path):
        p = profile_of(settings, tmp_path, {
            "frontend/package.json": '{"scripts": {"test": "jest"}, "devDependencies": {"jest": "29"}}',
            "frontend/a.js": "x\n", "frontend/b.js": "y\n",
        })
        assert p.test_commands == ["cd frontend && npm test"]

    @pytest.mark.parametrize("files,framework,command", [
        ({"Cargo.toml": '[package]\nname="x"\n\n[dependencies]\ntokio = "1"\naxum = "0.7"\n', "src/main.rs": "fn main() {}\n"}, "Axum", "cargo test"),
        ({"composer.json": '{"require": {"php": "^8", "laravel/framework": "^11"}, "require-dev": {"phpunit/phpunit": "^10"}}', "app/User.php": "<?php\n"}, "Laravel", "./vendor/bin/phpunit"),
        ({"Gemfile": "gem 'rails'\ngem 'rspec-rails'\n", "app/user.rb": "class User; end\n"}, "Ruby on Rails", "bundle exec rspec"),
        ({"pom.xml": "<project><artifactId>demo</artifactId><dependencies><artifactId>spring-boot-starter</artifactId><artifactId>junit</artifactId></dependencies></project>", "src/Main.java": "class Main {}\n"}, "Spring Boot", "mvn test"),
        ({"App.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web"><PackageReference Include="xunit" /></Project>', "Program.cs": "class P {}\n"}, "ASP.NET Core", "dotnet test"),
    ])
    def test_other_ecosystems(self, settings, tmp_path, files, framework, command):
        p = profile_of(settings, tmp_path, files)
        assert p.supported and framework in p.frameworks and command in p.test_commands

    def test_python_frameworks_and_commands(self, settings, tmp_path):
        p = profile_of(settings, tmp_path, {
            "requirements.txt": "fastapi==0.110\npydantic>=2\npytest\n", "app/main.py": "x = 1\n", "tests/test_main.py": "def test_x():\n    pass\n",
        })
        assert {"FastAPI", "Pydantic"} <= set(p.frameworks)
        assert p.test_commands[0] == "pytest" and p.validation_language == "Python"

    def test_detection_never_executes_or_crashes_on_bad_manifests(self, settings, tmp_path):
        info = detect_stack(index_of(settings, tmp_path, {"package.json": "{not json", "composer.json": "[]", "x.py": "1\n"}))
        assert info.frameworks == [] and info.test_commands == []


class TestFramesAndOutlines:
    def frames(self, settings, tmp_path, files, trace):
        index = index_of(settings, tmp_path, files)
        return [(f.path, f.line) for f in RepositoryAnalyzer().extract_frames(trace, index)]

    def test_frames_from_many_ecosystems(self, settings, tmp_path):
        files = {
            "src/main/java/com/acme/Cart.java": "class Cart {}\n", "pkg/cart/cart.go": "package cart\n", "src/lib.rs": "fn x() {}\n",
            "app/Models/User.php": "<?php\n", "lib/login.dart": "class L {}\n", "Sources/Home.swift": "struct H {}\n",
            "Services/Pay.cs": "class Pay {}\n", "app/user.rb": "class U; end\n",
        }
        trace = (
            "Exception in thread main\n\tat com.acme.Cart.total(Cart.java:42)\n"
            "goroutine 1: /build/pkg/cart/cart.go:17 +0x1d\n"
            "thread 'main' panicked at src/lib.rs:9:5\n"
            "PHP Fatal error: Uncaught Error in /srv/app/Models/User.php on line 31\n"
            "#0 package:shop/login.dart 12:5\n"
            "Fatal error: Sources/Home.swift:88: Index out of range\n"
            "   at Pay.Charge() in /src/Services/Pay.cs:line 55\n"
            "app/user.rb:7:in `name'\n"
        )
        found = dict(self.frames(settings, tmp_path, files, trace))
        assert found == {
            "src/main/java/com/acme/Cart.java": 42, "pkg/cart/cart.go": 17, "src/lib.rs": 9, "app/Models/User.php": 31,
            "lib/login.dart": 12, "Sources/Home.swift": 88, "Services/Pay.cs": 55, "app/user.rb": 7,
        }

    def test_frames_ignore_names_that_are_not_in_the_repo(self, settings, tmp_path):
        assert self.frames(settings, tmp_path, {"a.go": "package a\n"}, "at Other.java:3 and elsewhere.go:9") == []

    def test_ranking_and_outline_work_for_non_python_files(self, settings, tmp_path):
        index = index_of(settings, tmp_path, {
            "src/Cart.kt": "class Cart {\n    fun applyDiscount(total: Double, percent: Double): Double {\n        return total - total * percent / 10\n    }\n}\n",
            "src/Other.kt": "class Other\n",
        })
        analyzer = RepositoryAnalyzer()
        ranked = analyzer.rank_files(index, analyzer.extract_keywords("applyDiscount takes off too much"), [], 5)
        assert ranked and ranked[0].path == "src/Cart.kt"
        outline = analyzer.outline("src/Cart.kt", index.read_text("src/Cart.kt"))
        assert "Cart (line 1)" in outline and "applyDiscount (line 2)" in outline

    def test_outline_for_typed_method_languages(self, settings):
        java = "public class Cart {\n    public double total(int items) {\n        if (items > 0) {\n            return 1;\n        }\n    }\n}\n"
        outline = RepositoryAnalyzer().outline("Cart.java", java)
        assert "Cart" in outline and "total" in outline and "if" not in outline


class TestProtectedPathsAcrossLanguages:
    @pytest.mark.parametrize("path", [
        "internal/cart/cart_test.go", "lib/login_test.dart", "app/src/test/java/CartTest.java", "Tests/AppTests.swift",
        "spec/user_spec.rb", "src/Cart.Tests/CartTests.cs", "pubspec.yaml", "app/build.gradle.kts", "Cargo.toml", "go.mod",
    ])
    def test_tests_and_manifests_cannot_be_patched(self, path):
        assert protected_reason(path)

    @pytest.mark.parametrize("path", ["internal/cart/cart.go", "lib/login.dart", "src/main/java/Cart.java", "Sources/Home.swift", "app/user.rb"])
    def test_source_files_can_be_patched(self, path):
        assert protected_reason(path) is None
