import re
import numpy
import codecs
import yaml
import textwrap
import logging
import cellprofiler
import cellprofiler.module
import cellprofiler.modules
import cellprofiler.preferences


log = logging.getLogger(__name__)


H_VERSION_LEGACY = 'Version'
H_PIPELINE_VERSION = 'PipelineVersion'
H_CP_VERSION = 'CellProfilerVersion'

# The current pipeline file format version
NATIVE_VERSION = 5

# The number of modules in the pipeline
H_MODULE_COUNT = "ModuleCount"

# Indicates whether the pipeline has an image plane details section
H_HAS_IMAGE_PLANE_DETAILS = "HasImagePlaneDetails"

# A message for a user, to be displayed when pipeline is loaded
H_MESSAGE_FOR_USER = "MessageForUser"

# The cookie that identifies a file as a CellProfiler pipeline
COOKIE_PREFIX = "CellProfiler Pipeline"
COOKIE_SUFFIX = "http://www.cellprofiler.org"

# Module list sentinal
H_MODULE_LIST = "Module List"
# File list sentinal
H_FILE_LIST = "File List"

# Private module attributes
M_PRIVATE_ATTRIBUTES = "Private module attributes"
M_MODULE_NUMBER = 'module_num'
M_SVN_VERSION = 'svn_version'
M_VARIABLE_REVISION = 'variable_revision_number'
M_SHOW_WINDOW = 'show_window'
M_NOTES = 'notes'
M_BATCH_STATE = 'batch_state'
M_ENABLED = 'enabled'
M_WANTS_PAUSE = 'wants_pause'


class PipelineLoadException(Exception):
    pass


def save_yaml(modules, filename, file_list, modules_to_save=None, save_image_plane_details=True):

    # Don't write image plane details if we don't have any
    if len(file_list) == 0:
        save_image_plane_details = False

    pipeline_dict = {
        COOKIE_PREFIX: COOKIE_SUFFIX,
        H_CP_VERSION: cellprofiler.__version__,
        H_PIPELINE_VERSION: NATIVE_VERSION,
        H_MODULE_COUNT: len(modules),
        H_HAS_IMAGE_PLANE_DETAILS: save_image_plane_details,
        H_MODULE_LIST: []
    }

    if save_image_plane_details:
        pass

    attributes = (M_MODULE_NUMBER, M_SVN_VERSION, M_VARIABLE_REVISION, M_SHOW_WINDOW,
                  M_NOTES, M_BATCH_STATE, M_ENABLED, M_WANTS_PAUSE)

    # For now, I'm going to try and get feature parity with the savetxt function
    # TODO: This but better
    for module in modules:
        if modules_to_save is not None and module.module_num not in modules_to_save:
            continue

        # Private module attributes should be at the end
        module_dict = {setting.text: setting.unicode_value for setting in module.settings()}

        module_dict.update({
            M_PRIVATE_ATTRIBUTES: {
                attribute: getattr(module, attribute) for attribute in attributes
            }
        })

        # Safe yaml doesn't like numpy arrays
        module_dict[M_PRIVATE_ATTRIBUTES][M_BATCH_STATE] = module_dict[M_PRIVATE_ATTRIBUTES][M_BATCH_STATE].dumps()

        # Note: it may seem wierd that we're adding dictionaries with a single key to
        # a list. If our modules list was actually a dictionary, users wouldn't be able
        # to add more than one instance of a module to the pipeline file, since they key
        # is the module name and that key has to be unique.
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


def load_yaml(filename, raise_on_error=False, notify_fn=lambda x: None):
    with codecs.open(filename, 'r', 'utf-8') as in_file:
        pipeline_dict = yaml.safe_load(in_file.readlines())

    if COOKIE_PREFIX not in pipeline_dict:
        # This isn't mission critical, we'll make that check below
        log.warning("Pipeline file {} may not be a valid CellProfiler pipeline".format(filename))

    is_headless = cellprofiler.preferences.get_headless()
    volumetric = False

    try:
        # Check pipeline file version
        pipeline_version = int(pipeline_dict[H_PIPELINE_VERSION])
        # From the __future__
        if pipeline_version > NATIVE_VERSION:
            raise PipelineLoadException(textwrap.dedent("""
                Pipeline file version is {}.
                CellProfiler can only read version {} or less.
                Please upgrade to the latest version of CellProfiler in order to use this pipeline.
            """.format(pipeline_version, NATIVE_VERSION)
            ))
        # Anything that needs to be done for previous versions can go here

        # Check the cellprofiler version
        cp_version = pipeline_dict[H_CP_VERSION]
        # TODO: Some means of string comparing semvers
        if cp_version < cellprofiler.__version__ and not is_headless:
            log.warning(textwrap.dedent("""
                Your pipeline was saved using an old version of CellProfiler (version {}). 
                The current version of CellProfiler can load and run this pipeline, 
                but if you make changes to it and save, the older version of CellProfiler 
                (perhaps the version your collaborator has?) may not be able to load it.
                You can ignore this warning if you do not plan to save this pipeline or 
                if you will only use it with this or later versions of CellProfiler.
            """.format(cp_version)))

        # Load the modules
        new_modules = []
        # Each module needs a position within the pipeline, which tells it which
        # 'step' it is. We want to be as permissive as we can when loading a pipeline
        # file, which means that even if some modules don't load, we still want to be
        # able to load the rest of the pipeline (albeit while warning the user).
        # We have to keep track of the module number ourselves to accomplish this,
        # hence why we can't just enumerate the pipeline dictionary and use that.
        module_number = 1
        for module_block in pipeline_dict[H_MODULE_LIST]:
            # Module name should be the first and only key for the module block
            module_name = module_block.keys()[0]
            module_info = module_block[module_name]

            try:
                # Initiate the module
                module = cellprofiler.modules.instantiate_module(module_name)

                # Set the private attributes
                attributes = (M_VARIABLE_REVISION, M_SHOW_WINDOW, M_NOTES, M_BATCH_STATE, M_ENABLED, M_WANTS_PAUSE)
                # Pop here because we don't want them added to the settings below
                private_attrs = module_info.pop(M_PRIVATE_ATTRIBUTES)
                # We need to load batch state back into a numpy array
                private_attrs[M_BATCH_STATE] = numpy.loads(private_attrs[M_BATCH_STATE])
                for attr_name, attr_value in private_attrs.items():
                    setattr(module, attr_name, attr_value)

                # Set the module specific attributes
                module.set_settings_from_values(module_info.values())

                # I'm really not a fan of this, but there isn't a better way to do this currently
                if module_name == "NamesAndTypes":
                    volumetric = module.process_as_3d.value

                # Finally, append and increment the module version number
                new_modules.append(module)
                module_number += 1

            except Exception as err:
                log.warning("Failed to load module {}-{}".format(module_name, module_number))
                if raise_on_error:
                    raise
                log.exception(err)
                log.warning("Continuing to load the rest of the pipeline")

        # TODO: Image plane details

    except KeyError as err:
        log.error("Unable to load pipeline file {}".format(err))
        log.exception(err)
        raise PipelineLoadException(err)
