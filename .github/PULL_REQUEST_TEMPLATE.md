## Summary

Brief description of what this PR does.

## Type of change

- [ ] Bug fix
- [ ] Documentation improvement
- [ ] CI / robustness
- [ ] Other

## Testing

How you tested this change (include commands if applicable).

## Checklist

- [ ] `python -m py_compile` / `python -m unittest discover -s tests -v` pass
- [ ] `python scripts/validate_schema.py --check-contract-sync` passes if prompts or the contract changed
- [ ] `bash -n` and `shellcheck --severity=warning` pass on modified `.sh` files
- [ ] No personal paths, API keys, or secrets committed
- [ ] Paths use `MEDIA_DIR` / `local.env` — do not sed-replace the repo
