"""Where things are on this computer, for scripts:
    python -m project logs     the folder for the service's logs
    python -m project where    every folder, as JSON"""
import json
import sys

import project
from project import runtime_data

if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "where"
    if what == "logs":
        print(project.logs_dir())
    else:
        print(json.dumps({"config": project.MACHINE, "edition": project.edition(), "data": project.data_home(),
                          "pack": project.active_pack(), "design": project.data_root(), "work": project.work_root(),
                          "runtime": project.runtime_dir(),
                          "runtime_format": runtime_data.read(project.runtime_dir()).get("format", 0),
                          "logs": project.logs_dir()}, ensure_ascii=False, indent=1))
