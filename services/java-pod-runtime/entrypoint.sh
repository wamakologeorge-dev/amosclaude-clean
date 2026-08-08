#!/usr/bin/env bash
set -Eeuo pipefail

workspace="${AMOSCLAUD_WORKSPACE:-/workspace}"
artifacts="${AMOSCLAUD_ARTIFACTS:-/artifacts}"
build_tool="${AMOSCLAUD_BUILD_TOOL:-auto}"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cache_root="$workspace/.amosclaud-cache"

mkdir -p "$workspace" "$artifacts" "$cache_root/m2" "$cache_root/gradle"
export MAVEN_OPTS="${MAVEN_OPTS:-} -Dmaven.repo.local=$cache_root/m2"
export GRADLE_USER_HOME="$cache_root/gradle"
cd "$workspace"

write_failure() {
  status=$?
  finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"status":"failed","exit_code":%s,"pipeline_id":"%s","java_pod_id":"%s","build_tool":"%s","started_at":"%s","finished_at":"%s"}\n' \
    "$status" "${AMOSCLAUD_PIPELINE_ID:-unknown}" "${AMOSCLAUD_JAVA_POD_ID:-unknown}" \
    "$build_tool" "$started_at" "$finished_at" > "$artifacts/pipefail.json"
  exit "$status"
}
trap write_failure ERR

run_build() {
  if [[ -n "${AMOSCLAUD_JAVA_COMMAND:-}" ]]; then
    bash -lc "$AMOSCLAUD_JAVA_COMMAND"
    return
  fi

  case "$build_tool" in
    maven)
      if [[ -x ./mvnw ]]; then ./mvnw -B verify; else mvn -B verify; fi
      ;;
    gradle)
      [[ -x ./gradlew ]] || { echo "Gradle wrapper is required" >&2; return 64; }
      ./gradlew --no-daemon build
      ;;
    javac)
      mapfile -t sources < <(find . -type f -name '*.java' -not -path './.git/*' | sort)
      ((${#sources[@]})) || { echo "No Java sources found" >&2; return 66; }
      mkdir -p "$artifacts/classes"
      javac -d "$artifacts/classes" "${sources[@]}"
      ;;
    auto)
      if [[ -x ./mvnw || -f pom.xml ]]; then
        if [[ -x ./mvnw ]]; then ./mvnw -B verify; else mvn -B verify; fi
      elif [[ -x ./gradlew ]]; then
        ./gradlew --no-daemon build
      else
        build_tool=javac
        mapfile -t sources < <(find . -type f -name '*.java' -not -path './.git/*' | sort)
        ((${#sources[@]})) || { echo "No Maven, Gradle, or Java source input found" >&2; return 66; }
        mkdir -p "$artifacts/classes"
        javac -d "$artifacts/classes" "${sources[@]}"
      fi
      ;;
    *)
      echo "Unsupported build tool: $build_tool" >&2
      return 64
      ;;
  esac
}

run_build

find target build/libs -maxdepth 2 -type f \( -name '*.jar' -o -name '*.war' \) \
  -exec cp -f '{}' "$artifacts/" \; 2>/dev/null || true

finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"status":"completed","pipeline_id":"%s","java_pod_id":"%s","build_tool":"%s","jdk":"%s","started_at":"%s","finished_at":"%s"}\n' \
  "${AMOSCLAUD_PIPELINE_ID:-unknown}" "${AMOSCLAUD_JAVA_POD_ID:-unknown}" \
  "$build_tool" "${AMOSCLAUD_JDK:-21}" "$started_at" "$finished_at" \
  > "$artifacts/result.json"
