"""Expose startup Python stack if initialization spends time waiting on I/O."""
if __name__ == '__main__':
    import faulthandler
    faulthandler.enable()
    import os
    if os.environ.get("PD_TRACE_STARTUP") == "1":
        faulthandler.dump_traceback_later(30,repeat=True)
    from vllm.entrypoints.cli.main import main
    main()
