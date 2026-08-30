# Shared interpreter resolution for scripts/. Source after setting ROOT.
if [[ -n "${KOIS_PYTHON:-}" ]]; then
  PYTHON="$KOIS_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
