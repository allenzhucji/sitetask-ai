from app.application import run


if __name__ == "__main__":
    import sys
    if '--self-test' in sys.argv:
        from app.diagnostics import self_test
        raise SystemExit(self_test(sys.argv[1:]))
    raise SystemExit(run())
