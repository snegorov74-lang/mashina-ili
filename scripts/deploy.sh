#!/usr/bin/env bash
# Публикация сайта: переносит ветку main в ветку deploy, из которой GitHub Pages собирает сайт.
# Публикуется только то, что уже закоммичено и отправлено в origin/main.
# Запуск: scripts/deploy.sh          — опубликовать текущий origin/main
#         scripts/deploy.sh <коммит>  — опубликовать конкретный коммит (например, откатиться)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

git fetch -q origin
ref="${1:-origin/main}"
sha="$(git rev-parse --verify "$ref^{commit}")"

# Без обязательных файлов сайт не откроется — проверяем их в публикуемом коммите.
for f in index.html 3d.html assets/css/site.css assets/js/site.js assets/js/explorer.js \
         data/parts.js data/garage.js data/glossary.js model/sevor.glb .nojekyll; do
  git cat-file -e "$sha:$f" 2>/dev/null || { echo "Нет файла $f в $ref — публикация отменена."; exit 1; }
done

current="$(git rev-parse -q --verify origin/deploy || true)"
if [ "$current" = "$sha" ]; then echo "Этот коммит уже опубликован."; exit 0; fi

if [ -n "${1:-}" ]; then
  # Явно указанный коммит (откат) может быть не потомком deploy.
  git push --force-with-lease=deploy:"$current" origin "$sha:refs/heads/deploy"
else
  git push origin "$sha:refs/heads/deploy"
fi
echo "Опубликовано: $(git log -1 --format='%h %s' "$sha")"
echo "Сайт обновится через 1–2 минуты: https://snegorov74-lang.github.io/mashina-ili/"
