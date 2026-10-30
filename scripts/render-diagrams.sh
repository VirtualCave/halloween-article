#!/usr/bin/env sh
# Renderiza cada diagrams/*.d2 en images/*.svg.
# Usa Montserrat (la tipografía de Virtual Cave) si la encuentra; si no, la fuente por defecto de D2.
# Uso: sh scripts/render-diagrams.sh [diagrama.d2 ...]
#   FONT_DIR   carpeta con los .ttf de Montserrat (por defecto ~/Library/Fonts y ~/.local/share/fonts)
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v d2 >/dev/null 2>&1 || { echo "MISSING d2: instala D2 (https://d2lang.com/tour/install)"; exit 1; }

find_font() {
  for dir in ${FONT_DIR:-} "$HOME/Library/Fonts" "$HOME/.local/share/fonts" /Library/Fonts /usr/share/fonts; do
    for name in "$@"; do
      [ -f "$dir/$name" ] && { echo "$dir/$name"; return 0; }
    done
  done
  return 1
}

if regular=$(find_font Montserrat-Regular.ttf Montserrat-400.ttf); then
  export D2_FONT_REGULAR="$regular"
  export D2_FONT_ITALIC="$regular"
  D2_FONT_SEMIBOLD=$(find_font Montserrat-SemiBold.ttf Montserrat-600.ttf || echo "$regular")
  D2_FONT_BOLD=$(find_font Montserrat-Bold.ttf Montserrat-700.ttf || echo "$D2_FONT_SEMIBOLD")
  export D2_FONT_SEMIBOLD D2_FONT_BOLD
  echo "fuente: Montserrat ($(dirname "$regular"))"
else
  echo "fuente: Montserrat no encontrada, uso la de D2 (define FONT_DIR para cambiarlo)"
fi

[ $# -gt 0 ] || set -- "$root"/diagrams/[0-9]*.d2
status=0
for src in "$@"; do
  name=$(basename "$src" .d2)
  if d2 --omit-version --pad 48 "$src" "$root/images/$name.svg" >"$root/images/.$name.log" 2>&1; then
    echo "ok $name.svg"
    rm -f "$root/images/.$name.log"
  else
    echo "ERROR $name: $(tail -n 3 "$root/images/.$name.log")"
    status=1
  fi
done
[ $status -eq 0 ] && echo "RENDER OK" || echo "RENDER: hay errores"
exit $status
