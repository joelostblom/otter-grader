"""
Gradescope autograder configuration generator for Otter Generate
"""

import os
import json
import shutil
# import subprocess
import zipfile
import tempfile
import pathlib
import pkg_resources

from glob import glob
from subprocess import PIPE
from jinja2 import Template

from .token import APIClient
from ..plugins import PluginCollection
from ..run.run_autograder.constants import DEFAULT_OPTIONS

TEMPLATE_DIR = pkg_resources.resource_filename(__name__, "templates")
MINICONDA_INSTALL_URL = "https://repo.anaconda.com/miniconda/Miniconda3-py37_4.8.3-Linux-x86_64.sh"
OTTER_ENV_NAME = "otter-gradescope-env"

def main(tests_path, output_path, config, lang, requirements, overwrite_requirements, username, 
        password, files, assignment=None, **kwargs):
    """
    Runs ``otter generate autograder``
    """
    # read in otter_config.json
    if config is None and os.path.isfile("otter_config.json"):
        config = "otter_config.json"

    assert config is None or os.path.isfile(config), f"Could not find otter configuration file {config}"

    if config:
        with open(config) as f:
            otter_config = json.load(f)
    else:
        otter_config = {}
    
    if "course_id" in otter_config and "assignment_id" in otter_config:
        client = APIClient()
        if username is not None and password is not None:
            client.log_in(username, password)
            token = client.token
        else:
            token = client.get_token()
        otter_config["token"] = token
    elif "course_id" in otter_config or "assignment_id" in otter_config:
        raise ValueError(f"Otter config contains 'course_id' or 'assignment_id' but not both")

    options = DEFAULT_OPTIONS.copy()
    options.update(otter_config)

    # update language
    options["lang"] = lang.lower()

    template_dir = os.path.join(TEMPLATE_DIR, options["lang"])

    templates = {}
    for fn in os.listdir(template_dir):
        fp = os.path.join(template_dir, fn)
        with open(fp) as f:
            templates[fn] = Template(f.read())

    template_context = {
        "autograder_dir": options['autograder_dir'],
        "otter_env_name": OTTER_ENV_NAME,
        "miniconda_install_url": MINICONDA_INSTALL_URL,
        "ottr_branch": "stable",
    }

    plugins = PluginCollection(otter_config.get("plugins", []), None, {})
    plugins.run("during_generate", otter_config, assignment)

    # create tmp directory to zip inside
    with tempfile.TemporaryDirectory() as td:

        # try:
        # copy tests into tmp
        test_dir = os.path.join(td, "tests")
        os.mkdir(test_dir)
        pattern = ("*.py", "*.[Rr]")[options["lang"] == "r"]
        for file in glob(os.path.join(tests_path, pattern)):
            shutil.copy(file, test_dir)

        # open requirements if it exists
        requirements = requirements
        reqs_filename = f"requirements.{'R' if options['lang'] == 'r' else 'txt'}"
        if requirements is None and os.path.isfile(reqs_filename):
            requirements = reqs_filename
        
        if requirements:
            assert os.path.isfile(requirements), f"Requirements file {requirements} not found"
            f = open(requirements)
        else:
            f = open(os.devnull)

        template_context["other_requirements"] = f.read()
        template_context["overwrite_requirements"] = overwrite_requirements

        rendered = {}
        for fn, tmpl in templates.items():
            rendered[fn] = tmpl.render(**template_context)

        # close the stream
        f.close()

        if os.path.isabs(output_path):
            zip_path = os.path.join(output_path, "autograder.zip")
        else:
            zip_path = os.path.join(os.getcwd(), output_path, "autograder.zip")
        
        if os.path.exists(zip_path):
            os.remove(zip_path)

        with zipfile.ZipFile(zip_path, mode="w") as zf:
            for fn, contents in rendered.items():
                zf.writestr(fn, contents)

            test_dir = "tests"
            pattern = ("*.py", "*.[Rr]")[options["lang"] == "r"]
            for file in glob(os.path.join(tests_path, pattern)):
                zf.write(file, arcname=os.path.join(test_dir, os.path.basename(file)))
            
            zf.writestr("otter_config.json", json.dumps(otter_config, indent=2))

            # copy files into tmp
            if len(files) > 0:
                for file in files:
                    full_fp = os.path.abspath(file)
                    assert os.getcwd() in full_fp, f"{file} is not in a subdirectory of the working directory"
                    zf.write(file, arcname=os.path.join("files", file))
