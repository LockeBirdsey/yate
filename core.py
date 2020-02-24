import json
import logging
import multiprocessing

# To make pyinstaller behave
multiprocessing.freeze_support()
import subprocess
import platform
import sys
import threading
from datetime import datetime
from queue import Queue
from threading import Thread

from constants import *

import zipimport

##
# Sorry for anyone who looks at this.
# I need to get around to refactoring
# and this is nowhere near as bad as builder.py...
# lb
##
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)


class Core:
    log_queue = None
    logger = None
    queue_handler = None

    def __init__(self):
        self.logger = logging.getLogger('TweGeT')
        logging.basicConfig(level=logging.DEBUG)
        self.log_queue = Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        self.logger.addHandler(self.queue_handler)

    ON_POSIX = 'posix' in sys.builtin_module_names

    LIB_DICT_NAME = "libs"
    PROJECT_DICT_NAME = "project"
    AUTHOR_DICT_NAME = "author"
    UPDATED_TIME_KEY = "last_updated_at"
    BUILD_DIR_KEY = "build_directory"
    libs = {
        NPM_LOCATION: "",
        NPX_LOCATION: "",
        TWEEGO_LOCATION: ""
    }

    project = {
        PROJ_NAME: "",
        PROJ_DIR: "",
        PROJ_HTML: "",
        PROJ_PARENT_DIR: "",
        PROJ_BUILD_DIR: "",
        PROJ_VERSION: "1.0.0",
        PROJ_DIMS_HEIGHT: "600",
        PROJ_DIMS_WIDTH: "800",
        PROJ_ICON_LOCATION: "",
        PROJ_KEYWORDS: "",
        PROJ_LAST_UPDATED: ""
    }

    author = {
        AUTHOR_NAME: "Your Name",
        AUTHOR_EMAIL: "",
        AUTHOR_REPO: "",
    }

    entry_size = (20, 1)
    # The central YATE class
    system_type = platform.system()

    # System dependent variables
    which_command = "which"
    shell = False

    lock = threading.Lock()
    cmd_extension = ""
    WINDOWS_CMD_EXT = ".cmd"

    # I cannot find a nicer way of doing this without installing additional packages
    processes = []

    if system_type == "Windows":
        which_command = "where"
        shell = True
        cmd_extension = WINDOWS_CMD_EXT

    def enqueue_output(self, out, queue):
        for line in iter(out.readline, b''):
            self.logger.info(str(line, encoding="utf-8"))
        out.close()
        self.lock.release()

    def get_bin_path(self, app_name):
        try:
            proc = self.test_existence(app_name)
            location = proc.split("\n")[0].strip()
            return app_name, location
        except AssertionError:
            return app_name, ""
            # We have a result, now grab the first line of output
            # Windows note: the first location returned /tends/ to be the binary itself

    def run_command_with_output(self, commands, cwd=None):
        process = subprocess.Popen(commands, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False,
                                   bufsize=0, text=None, cwd=cwd)
        self.processes.append(process)
        t = Thread(target=self.enqueue_output, args=(process.stdout, self.log_queue))
        self.lock.acquire(blocking=False)
        t.start()

    # Warning: Blocking
    def run_command_store_output(self, commands, cwd=None):
        process = subprocess.Popen(commands, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False,
                                   bufsize=0, text=None, cwd=cwd)
        output = ""
        for line in iter(process.stdout.readline, b''):
            output += str(line, encoding="utf-8")
        process.stdout.close()
        return output

    def find_dependencies(self):
        res = self.get_bin_path(NPM)
        if res[1] == "":
            self.logger.info(
                "NPM cannot be found. It == likely not installed. Please visit https://www.npmjs.com/get-npm to install")
        self.libs[NPM_LOCATION] = res[1]
        self.lib_warning(res)

        res = self.get_bin_path(NPX)
        if res[1] == "":
            self.logger.info(
                "NPX cannot be found. It == likely not installed. Please visit https://www.npmjs.com/get-npm to install")
        self.libs[NPX_LOCATION] = res[1]
        self.lib_warning(res)

        res = self.get_bin_path(TWEEGO)
        self.libs[TWEEGO_LOCATION] = res[1]
        if res[1] == "":
            self.logger.info(
                "Tweego cannot be found. Either locate its executable or install from https://www.motoslave.net/tweego/")
        self.lib_warning(res)
        # TODO Still need to test for StoryFormats

    def lib_warning(self, app):
        name = app[0]
        state = app[1]
        if state != "":
            self.logger.info(name + " found at " + state)
        else:
            self.logger.info(name + " was unable to be located.")

    def test_existence(self, app_name):
        the_process = subprocess.run([self.which_command, app_name], universal_newlines=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=self.shell)
        assert (the_process.stderr == '')
        return the_process.stdout

    def create_lock_file(self, path):
        publish_time_stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        build_dir = str(path)

        # Build the data before writing it to file
        data = {self.UPDATED_TIME_KEY: publish_time_stamp, self.BUILD_DIR_KEY: build_dir,
                self.AUTHOR_DICT_NAME: self.author, self.LIB_DICT_NAME: self.libs, self.PROJECT_DICT_NAME: self.project}
        with open(path.joinpath(DETAILS_FILE_NAME), 'w', encoding="utf-8") as f:
            json.dump(data, fp=f, ensure_ascii=False, indent=4, sort_keys=True)

    def load_lock_file(self, path):
        # returns a tuple of the dictionaries
        # This method ensures that dictionary structure won't be affected
        with open(path, 'r', encoding="utf-8") as f:
            data = json.load(f)
            self.libs = data[self.LIB_DICT_NAME]
            self.project = data[self.PROJECT_DICT_NAME]
            self.author = data[self.AUTHOR_DICT_NAME]

    def update_package_json(self, path):
        data = None
        with open(path, 'r', encoding="utf-8") as f:
            data = json.load(f)
            # keywords = data["keywords"]
            data["keywords"] = self.project[PROJ_KEYWORDS].split(",")
            data["author"]["name"] = self.author[AUTHOR_NAME]
            data["author"]["email"] = self.author[AUTHOR_EMAIL]
            data["repository"] = self.author[AUTHOR_EMAIL]
            data["version"] = self.project[PROJ_VERSION]
            data["config"]["forge"]["packagerConfig"] = {"icon": "icon"}
        with open(path, 'w', encoding="utf-8") as f:
            json.dump(data, fp=f, indent=4)

    def terminate_processes(self):
        # this == ugly but it'll work until I improve it
        self.logger.info("Ending other tasks")
        for p in self.processes:
            if p.returncode is None:
                p.terminate()
        self.logger.info("All tasks finished, can safely close now\nHave a nice day :)")

    def replace_js_parameters(self, path):
        js = None
        with open(INDEX_JS_TEMPLATE_PATH, 'r') as f:
            js = f.read()
        js = js.replace(JS_HEIGHT_KEY, self.project[PROJ_DIMS_HEIGHT]).replace(JS_WIDTH_KEY,
                                                                               self.project[PROJ_DIMS_WIDTH])
        with open(path, 'w') as f:
            f.write(js)
