import re
import codecs
import cellprofiler


H_VERSION = 'Version'
H_SVN_REVISION = 'SVNRevision'
H_DATE_REVISION = 'DateRevision'

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


def save_yaml(pipeline, filename, modules_to_save=None, save_image_plane_details=True):

    # Don't write image plane details if we don't have any
    if len(pipeline.__Pipeline_file_list) == 0:
        save_image_plane_details = False

    pipeline_dict = {
        COOKIE_PREFIX: COOKIE_SUFFIX,
        H_VERSION: NATIVE_VERSION,
        H_DATE_REVISION: int(re.sub(r"\.|rc\d{1}", "", cellprofiler.__version__)),
        H_MODULE_COUNT: len(pipeline.__Pipeline__modules),
        H_HAS_IMAGE_PLANE_DETAILS: save_image_plane_details,
        H_MODULE_LIST: []
    }

    attributes = ('module_num', 'svn_version', 'variable_revision_number',
                  'show_window', 'notes', 'batch_state', 'enabled', 'wants_pause')

    # For now, I'm going to try and get feature parity with the savetxt function
    # TODO: This but better
    for module in pipeline.__Pipeline__modules:
        if modules_to_save is not None and module.module_num not in modules_to_save:
            continue

        # Private module attributes should be at the end
        module_dict = {setting.text: setting.unicode_value for setting in module.settings()}

        module_dict.update({
            "Private module attributes": {
                attribute: getattr(module, attribute) for attribute in attributes
            }
        })

        pipeline_dict[H_MODULE_LIST].append({module.module_name: module_dict})

    with codecs.open(filename, "w", 'utf-8'):
        pass

