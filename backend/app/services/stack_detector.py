"""Detects frameworks, dependencies, test frameworks and test commands from manifests and imports, for any language.

Nothing here runs repository code: manifests are read as text (JSON is parsed, everything else is matched with
patterns). Test commands are *inferred* and shown to the user for information. RepoPilot only executes tests for
Python, so every other command is reported as detected but not run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from app.services.repository_service import RepoIndex

MAX_MANIFEST_BYTES = 120_000
MAX_DEPTH = 3  # ignore manifests buried deeper than this (vendored examples, fixtures, generated code)

JS_FRAMEWORKS = {
    "next": "Next.js", "react": "React", "react-native": "React Native", "expo": "Expo", "vue": "Vue", "nuxt": "Nuxt",
    "@angular/core": "Angular", "svelte": "Svelte", "@sveltejs/kit": "SvelteKit", "express": "Express",
    "fastify": "Fastify", "@nestjs/core": "NestJS", "koa": "Koa", "electron": "Electron", "gatsby": "Gatsby",
    "astro": "Astro", "@remix-run/react": "Remix", "solid-js": "SolidJS", "tailwindcss": "Tailwind CSS",
    "@prisma/client": "Prisma", "typeorm": "TypeORM", "mongoose": "Mongoose", "graphql": "GraphQL", "vite": "Vite",
}
JS_TEST_TOOLS = {
    "jest": "jest", "vitest": "vitest", "mocha": "mocha", "jasmine": "jasmine", "ava": "ava",
    "@playwright/test": "playwright", "cypress": "cypress",
}
PY_FRAMEWORKS = {
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "starlette": "Starlette", "pydantic": "Pydantic",
    "sqlalchemy": "SQLAlchemy", "celery": "Celery", "numpy": "NumPy", "pandas": "pandas", "torch": "PyTorch",
    "tensorflow": "TensorFlow", "scikit-learn": "scikit-learn", "aiohttp": "aiohttp", "streamlit": "Streamlit",
}
DART_PACKAGES = {
    "provider": "Provider", "flutter_riverpod": "Riverpod", "riverpod": "Riverpod", "flutter_bloc": "BLoC", "bloc": "BLoC",
    "get": "GetX", "go_router": "go_router", "firebase_core": "Firebase", "dio": "Dio",
}
GO_FRAMEWORKS = {
    "gin-gonic/gin": "Gin", "labstack/echo": "Echo", "gofiber/fiber": "Fiber", "gorilla/mux": "Gorilla Mux",
    "google.golang.org/grpc": "gRPC", "gorm.io/gorm": "GORM", "spf13/cobra": "Cobra",
}
RUST_CRATES = {
    "tokio": "Tokio", "actix-web": "Actix Web", "axum": "Axum", "rocket": "Rocket", "diesel": "Diesel", "sqlx": "SQLx",
    "clap": "clap", "bevy": "Bevy", "tauri": "Tauri",
}
PHP_FRAMEWORKS = {
    "laravel/framework": "Laravel", "symfony/framework-bundle": "Symfony", "slim/slim": "Slim",
    "cakephp/cakephp": "CakePHP", "livewire/livewire": "Livewire",
}
GRADLE_MARKERS = {
    "com.android.application": "Android", "com.android.library": "Android", "androidx.compose": "Jetpack Compose",
    "org.springframework.boot": "Spring Boot", "io.ktor": "Ktor", "io.micronaut": "Micronaut", "io.quarkus": "Quarkus",
}
SWIFT_IMPORTS = {
    "SwiftUI": "SwiftUI", "UIKit": "UIKit", "AppKit": "AppKit", "Combine": "Combine", "SwiftData": "SwiftData",
    "CoreData": "Core Data",
}


@dataclass
class StackInfo:
    frameworks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    test_frameworks: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)

    def add(self, *, frameworks=(), dependencies=(), tests=(), commands=()) -> None:
        for target, items in ((self.frameworks, frameworks), (self.dependencies, dependencies),
                              (self.test_frameworks, tests), (self.test_commands, commands)):
            for item in items:
                if item and item not in target:
                    target.append(item)


def _depth(path: str) -> int:
    return len(PurePosixPath(path).parts) - 1


def _found(index: RepoIndex, *names: str, suffix: str | None = None) -> list[str]:
    """Shallowest-first paths whose file name is one of ``names`` (or ends with ``suffix``)."""
    wanted = set(names)
    hits = [
        f.path for f in index.files
        if _depth(f.path) <= MAX_DEPTH and (f.path.rsplit("/", 1)[-1] in wanted or (suffix and f.path.endswith(suffix)))
    ]
    return sorted(hits, key=lambda p: (_depth(p), p))


def _read(index: RepoIndex, path: str) -> str:
    try:
        return index.read_text(path, max_bytes=MAX_MANIFEST_BYTES)
    except Exception:  # noqa: BLE001 - an unreadable manifest is simply not used
        return ""


def _cmd(path: str, command: str) -> str:
    """A command prefixed with the manifest's directory when the project is not at the repository root."""
    directory = str(PurePosixPath(path).parent)
    return command if directory in ("", ".") else f"cd {directory} && {command}"


def detect_stack(index: RepoIndex) -> StackInfo:
    info = StackInfo()
    _javascript(index, info)
    _python(index, info)
    _dart(index, info)
    _jvm(index, info)
    _swift(index, info)
    _go(index, info)
    _rust(index, info)
    _php(index, info)
    _ruby(index, info)
    _dotnet(index, info)
    _cpp(index, info)
    paths = {f.path for f in index.files}
    if any(p.startswith("android/") for p in paths) and "Flutter" in info.frameworks:
        info.add(frameworks=["Android"])
    if any(p.startswith("ios/") for p in paths) and "Flutter" in info.frameworks:
        info.add(frameworks=["iOS"])
    info.frameworks = info.frameworks[:12]
    info.dependencies = info.dependencies[:16]
    info.test_commands = info.test_commands[:5]
    return info


# --- per ecosystem -----------------------------------------------------------------------------------------

def _javascript(index: RepoIndex, info: StackInfo) -> None:
    for path in _found(index, "package.json")[:4]:
        try:
            data = json.loads(_read(index, path) or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        prod = [k for k in (data.get("dependencies") or {}) if isinstance(k, str)]
        dev = [k for k in (data.get("devDependencies") or {}) if isinstance(k, str)]
        names = set(prod + dev + list(data.get("peerDependencies") or {}))
        info.add(
            frameworks=[label for dep, label in JS_FRAMEWORKS.items() if dep in names],
            dependencies=prod[:10],
            tests=[label for dep, label in JS_TEST_TOOLS.items() if dep in names],
        )
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        if "test" in scripts and "no test specified" not in str(scripts["test"]):
            info.add(commands=[_cmd(path, "npm test")])
        elif "vitest" in names:
            info.add(commands=[_cmd(path, "npx vitest run")])
        elif "jest" in names:
            info.add(commands=[_cmd(path, "npx jest")])


def _python(index: RepoIndex, info: StackInfo) -> None:
    manifests = _found(index, "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile", "setup.py")[:5]
    text = "\n".join(_read(index, p) for p in manifests).lower()
    if not text:
        return
    info.add(
        frameworks=[label for key, label in PY_FRAMEWORKS.items() if re.search(rf"(?<![\w\-]){re.escape(key)}(?![\w\-])", text)],
        dependencies=[n for p in manifests if p.endswith(".txt") for n in _requirement_names(_read(index, p))][:10],
    )


def _requirement_names(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)", line)
        if match and not line.lstrip().startswith(("-", "#")):
            out.append(match.group(1))
    return out


def _dart(index: RepoIndex, info: StackInfo) -> None:
    for path in _found(index, "pubspec.yaml")[:2]:
        text = _read(index, path)
        flutter = bool(re.search(r"^\s*sdk:\s*flutter\b", text, re.M) or re.search(r"^flutter:", text, re.M))
        packages = re.findall(r"^  ([a-z_][a-z0-9_]*):", text, re.M)
        info.add(
            frameworks=["Flutter" if flutter else "Dart", *[DART_PACKAGES[p] for p in packages if p in DART_PACKAGES]],
            dependencies=[p for p in packages if p not in ("flutter", "flutter_test", "sdk")][:10],
        )
        if "flutter_test" in text or any(f.path.endswith("_test.dart") for f in index.files):
            info.add(tests=["flutter_test" if flutter else "package:test"], commands=[_cmd(path, "flutter test" if flutter else "dart test")])


def _jvm(index: RepoIndex, info: StackInfo) -> None:
    gradle = _found(index, "build.gradle", "build.gradle.kts")
    for path in gradle[:3]:
        text = _read(index, path)
        info.add(
            frameworks=[label for marker, label in GRADLE_MARKERS.items() if marker in text],
            dependencies=[m for m in re.findall(r"""(?:implementation|api)\s*\(?\s*["']([\w.\-]+:[\w.\-]+)""", text)][:10],
            tests=[label for key, label in (("junit", "JUnit"), ("mockk", "MockK"), ("mockito", "Mockito"), ("espresso", "Espresso"), ("kotest", "Kotest")) if key in text.lower()],
        )
    if gradle:
        wrapper = any(f.path.rsplit("/", 1)[-1] == "gradlew" for f in index.files)
        info.add(frameworks=["Gradle"], commands=[_cmd(gradle[0], "./gradlew test" if wrapper else "gradle test")])
    if _found(index, "AndroidManifest.xml"):
        info.add(frameworks=["Android"])
    poms = _found(index, "pom.xml")
    for path in poms[:2]:
        text = _read(index, path)
        info.add(
            frameworks=["Maven", *(["Spring Boot"] if "spring-boot" in text else [])],
            dependencies=re.findall(r"<artifactId>([\w.\-]+)</artifactId>", text)[1:11],
            tests=["JUnit"] if "junit" in text.lower() else [],
        )
    if poms:
        info.add(commands=[_cmd(poms[0], "mvn test")])


def _swift(index: RepoIndex, info: StackInfo) -> None:
    swift_files = [f.path for f in index.files if f.language == "Swift"][:60]
    imports: set[str] = set()
    for path in swift_files:
        try:
            head = index.read_text(path, max_bytes=3000)
        except Exception:  # noqa: BLE001, S112
            continue
        imports.update(re.findall(r"^\s*import\s+(?:struct\s+|class\s+)?(\w+)", head, re.M))
    info.add(
        frameworks=[label for key, label in SWIFT_IMPORTS.items() if key in imports],
        tests=[*(["XCTest"] if "XCTest" in imports else []), *(["Swift Testing"] if "Testing" in imports else [])],
    )
    package = _found(index, "Package.swift")
    if package:
        info.add(frameworks=["Swift Package Manager"], commands=[_cmd(package[0], "swift test")])
    pbx = [f.path for f in index.files if f.path.endswith("project.pbxproj")][:1]
    if pbx:
        text = _read(index, pbx[0])
        info.add(
            frameworks=["Xcode", *(["iOS"] if "IPHONEOS_DEPLOYMENT_TARGET" in text else []),
                        *(["macOS"] if "MACOSX_DEPLOYMENT_TARGET" in text else [])],
        )
        if not package:
            info.add(commands=["xcodebuild test -scheme <your-scheme> -destination 'platform=iOS Simulator,name=iPhone 15'"])
    if _found(index, "Podfile"):
        info.add(frameworks=["CocoaPods"])


def _go(index: RepoIndex, info: StackInfo) -> None:
    mods = _found(index, "go.mod")
    for path in mods[:2]:
        text = _read(index, path)
        required = re.findall(r"^\s*(?:require\s+)?([\w.\-]+(?:/[\w.\-]+)+)\s+v[\w.\-+]+", text, re.M)
        info.add(
            frameworks=["Go modules", *[label for key, label in GO_FRAMEWORKS.items() if any(r.endswith(key) or key in r for r in required)]],
            dependencies=required[:10],
        )
    if mods and any(f.path.endswith("_test.go") for f in index.files):
        info.add(tests=["go test"], commands=[_cmd(mods[0], "go test ./...")])


def _rust(index: RepoIndex, info: StackInfo) -> None:
    cargo = _found(index, "Cargo.toml")
    for path in cargo[:2]:
        text = _read(index, path)
        match = re.search(r"^\[dependencies\]\s*\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
        crates = re.findall(r"^([A-Za-z0-9_\-]+)\s*=", match.group(1), re.M) if match else []
        info.add(frameworks=["Cargo", *[RUST_CRATES[c] for c in crates if c in RUST_CRATES]], dependencies=crates[:10])
    if cargo:
        info.add(tests=["cargo test"], commands=[_cmd(cargo[0], "cargo test")])


def _php(index: RepoIndex, info: StackInfo) -> None:
    for path in _found(index, "composer.json")[:2]:
        try:
            data = json.loads(_read(index, path) or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        require = [k for k in (data.get("require") or {}) if isinstance(k, str)]
        dev = [k for k in (data.get("require-dev") or {}) if isinstance(k, str)]
        info.add(
            frameworks=["Composer", *[label for key, label in PHP_FRAMEWORKS.items() if key in require]],
            dependencies=[r for r in require if r != "php"][:10],
        )
        if "phpunit/phpunit" in require + dev:
            info.add(tests=["PHPUnit"], commands=[_cmd(path, "./vendor/bin/phpunit")])
        if "pestphp/pest" in require + dev:
            info.add(tests=["Pest"], commands=[_cmd(path, "./vendor/bin/pest")])


def _ruby(index: RepoIndex, info: StackInfo) -> None:
    for path in _found(index, "Gemfile")[:1]:
        text = _read(index, path)
        gems = re.findall(r"^\s*gem\s+['\"]([\w\-]+)['\"]", text, re.M)
        info.add(
            frameworks=["Bundler", *(["Ruby on Rails"] if "rails" in gems else []), *(["Sinatra"] if "sinatra" in gems else [])],
            dependencies=gems[:10],
        )
        if "rspec" in gems or "rspec-rails" in gems:
            info.add(tests=["RSpec"], commands=[_cmd(path, "bundle exec rspec")])
        elif "minitest" in gems or any(f.path.startswith("test/") for f in index.files):
            info.add(tests=["Minitest"], commands=[_cmd(path, "bundle exec rake test")])


def _dotnet(index: RepoIndex, info: StackInfo) -> None:
    projects = _found(index, suffix=".csproj")
    for path in projects[:4]:
        text = _read(index, path)
        info.add(
            frameworks=[".NET", *(["ASP.NET Core"] if "Microsoft.NET.Sdk.Web" in text or "AspNetCore" in text else []),
                        *(["MAUI"] if "UseMaui" in text else []), *(["Blazor"] if "Blazor" in text else [])],
            dependencies=re.findall(r'<PackageReference\s+Include="([\w.\-]+)"', text)[:8],
            tests=[label for key, label in (("xunit", "xUnit"), ("nunit", "NUnit"), ("mstest", "MSTest")) if key in text.lower()],
        )
    if projects and any(t in {"xUnit", "NUnit", "MSTest"} for t in info.test_frameworks):
        info.add(commands=["dotnet test"])


def _cpp(index: RepoIndex, info: StackInfo) -> None:
    cmake = _found(index, "CMakeLists.txt")
    if cmake:
        text = _read(index, cmake[0]).lower()
        info.add(frameworks=["CMake"])
        if "enable_testing" in text or "add_test" in text or "gtest" in text or "catch2" in text:
            info.add(
                tests=[*(["GoogleTest"] if "gtest" in text or "googletest" in text else []), *(["Catch2"] if "catch2" in text else []), "CTest"],
                commands=[_cmd(cmake[0], "cmake -S . -B build && cmake --build build && ctest --test-dir build")],
            )
    for path in _found(index, "Makefile")[:1]:
        info.add(frameworks=["Make"])
        if re.search(r"^test\s*:", _read(index, path), re.M):
            info.add(commands=[_cmd(path, "make test")])
