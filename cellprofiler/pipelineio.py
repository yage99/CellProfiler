import re
import numpy
import codecs
import yaml
import cellprofiler


H_VERSION_LEGACY = 'Version'
H_VERSION = '_PipelineVersion'
H_SVN_REVISION = '_SVNRevision'
H_DATE_REVISION = '_DateRevision'
H_CP_VERSION = '_CellProfilerVersion'

# The current pipeline file format version
NATIVE_VERSION = 4

# The number of modules in the pipeline
H_MODULE_COUNT = "ModuleCount"

# Indicates whether the pipeline has an image plane details section
H_HAS_IMAGE_PLANE_DETAILS = "HasImagePlaneDetails"

# A message for a user, to be displayed when pipeline is loaded
H_MESSAGE_FOR_USER = "MessageForUser"

# The cookie that identifies a file as a CellProfiler pipeline
COOKIE_PREFIX = "CellProfiler Pipeline"
COOKIE_SUFFIX = "http://www.cellprofiler.org"
COOKIE = "{}: {}".format(COOKIE_PREFIX, COOKIE_SUFFIX)

# Module list sentinal
H_MODULE_LIST = "Module List"
# File list sentinal
H_FILE_LIST = "File List"

# Private module attributes
M_MODULE_ATTRIBUTES = "Private module attributes"


def save_yaml(modules, file_list, filename, modules_to_save=None, save_image_plane_details=True):

    # Don't write image plane details if we don't have any
    if len(file_list) == 0:
        save_image_plane_details = False

    pipeline_dict = {
        COOKIE_PREFIX: COOKIE_SUFFIX,
        H_CP_VERSION: cellprofiler.__version__,
        H_VERSION: NATIVE_VERSION,
        H_DATE_REVISION: int(re.sub(r"\.|rc\d{1}", "", cellprofiler.__version__)),
        H_MODULE_COUNT: len(modules),
        H_HAS_IMAGE_PLANE_DETAILS: save_image_plane_details,
        H_MODULE_LIST: []
    }

    if save_image_plane_details:
        pass

    attributes = ('module_num', 'svn_version', 'variable_revision_number',
                  'show_window', 'notes', 'batch_state', 'enabled', 'wants_pause')

    # For now, I'm going to try and get feature parity with the savetxt function
    # TODO: This but better
    for module in modules:
        if modules_to_save is not None and module.module_num not in modules_to_save:
            continue

        # Private module attributes should be at the end
        module_dict = {setting.text: setting.unicode_value for setting in module.settings()}

        module_dict.update({
            M_MODULE_ATTRIBUTES: {
                attribute: getattr(module, attribute) for attribute in attributes
            }
        })

        # safe yaml doesn't like arrays
        module_dict[M_MODULE_ATTRIBUTES]['batch_state'] = module_dict[M_MODULE_ATTRIBUTES]['batch_state'].dumps()

        pipeline_dict[H_MODULE_LIST].append({module.module_name: module_dict})

    if save_image_plane_details:
        # TODO: Functionality of write_file_list
        pass

    with codecs.open(filename, "w", 'utf-8') as out_file:
        # Use safe_dump here because we don't want yaml putting in all these
        # !!python/unicode imperatives all over the place. Additionally, this makes
        # it significantly more readable.
        # TODO: This doesn't preserve ordering...why?
        out_file.write(yaml.safe_dump(pipeline_dict))

