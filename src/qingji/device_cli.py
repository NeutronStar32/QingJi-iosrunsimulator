"""Adapt the upstream interactive hold to a controlled stdin session."""

import sys

if __name__ == "__main__":
    try:
        from pymobiledevice3.__main__ import main
        from pymobiledevice3.cli.cli_common import OSUTILS
    except ImportError as error:
        print(
            "手机组件未安装或不完整，请先安装 requirements.txt 中的依赖。\n" + str(error),
            file=sys.stderr,
        )
        sys.exit(1)

    if sys.argv[1:5] == ["developer", "dvt", "simulate-location", "stream"]:
        import asyncio
        import json
        import math

        from pymobiledevice3.cli.cli_common import ServiceProviderDep, async_command
        from pymobiledevice3.cli.developer.dvt.simulate_location import cli
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation

        def emit(event):
            print("QINGJI_EVENT " + json.dumps(event), flush=True)

        @cli.command("stream")
        @async_command
        async def stream(service_provider: ServiceProviderDep):
            async with DvtProvider(service_provider) as dvt, LocationSimulation(dvt) as simulation:
                emit({"event": "ready"})
                while True:
                    line = await asyncio.to_thread(sys.stdin.readline)
                    if not line:
                        return
                    request = {}
                    try:
                        request = json.loads(line)
                        if request.get("action") == "stop":
                            return
                        point = request.get("point")
                        if (
                            request.get("action") != "set"
                            or not isinstance(point, list)
                            or len(point) != 2
                            or any(
                                isinstance(v, bool)
                                or not isinstance(v, (int, float))
                                or not math.isfinite(v)
                                for v in point
                            )
                            or abs(point[0]) > 90
                            or abs(point[1]) > 180
                        ):
                            raise ValueError("坐标指令无效。")
                        await simulation.set(*point)
                        emit({"id": request.get("id"), "ok": True})
                    except Exception as error:
                        emit({"id": request.get("id"), "ok": False, "error": str(error)})

    def hold():
        print("LOCATION_SET_READY", flush=True)
        sys.stdin.readline()

    if sys.argv[1:5] == ["developer", "dvt", "simulate-location", "set"]:
        OSUTILS.wait_return = hold
    sys.exit(main())
