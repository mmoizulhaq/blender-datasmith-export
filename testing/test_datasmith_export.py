#
#
# datasmith export test suite
# run this file with the following command:
# blender -b sample_file.blend -P test_datasmith_export.py

import bpy.ops
import bpy
import os
import logging
import time
import shutil
logging_level = logging.INFO # WARNING, INFO, DEBUG
# logging_level = logging.DEBUG # WARNING, INFO, DEBUG

logging.basicConfig(
	level=logging_level,
	# format='%(asctime)s.%(msecs)03d %(name)-12s %(levelname)-8s %(message)s',
	format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
	datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger()

clean_path = os.path.normpath(bpy.data.filepath)

base_dir, file_name = os.path.split(clean_path)
name, ext = os.path.splitext(file_name)
target_path = os.path.join(base_dir, name + ".udatasmith")


log.info("basedir %s", base_dir)
use_diff = True
backup_path = None
if use_diff and os.path.isfile(target_path):
	log.info("backing up previous test")
	last_modification_time = os.path.getmtime(target_path)
	time_str = time.strftime('%Y%m%d_%H%M%S', time.localtime(last_modification_time))
	backup_path = os.path.join(base_dir, "%s_%s.udatasmith" % (name, time_str))
	log.debug("last modification was:%s", backup_path)
	shutil.copy(target_path, backup_path)

log.info("Starting automated export")

custom_args = {}
custom_args["experimental_tex_mode"] = True
custom_args["apply_modifiers"] = True


bpy.ops.export_scene.datasmith(filepath=target_path, **custom_args)
log.info("Ended automated export")

# right now this is not so useful as the export is non deterministic
# i guess it is because the usage of dictionaries

if backup_path:
	log.info("writing diff file")
	import difflib

	with open(backup_path) as ff:
		from_lines = ff.readlines()
	with open(target_path) as tf:
		to_lines = tf.readlines()

	diff = difflib.unified_diff(from_lines, to_lines, backup_path, target_path)

	new_modification_time = os.path.getmtime(target_path)
	new_time_str = time.strftime('%Y%m%d_%H%M%S', time.localtime(new_modification_time))
	diff_path = os.path.join(base_dir, "export_diff_%s.diff" % new_time_str)
	with open(diff_path, 'w') as diff_file:
		diff_file.writelines(diff)
	static_diff_path = os.path.join(base_dir, "export_diff.diff")
	shutil.copy(diff_path, static_diff_path)


