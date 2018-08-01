import codecs
import yaml
import textwrap
import logging
import distutils.version
import cellprofiler
import cellprofiler.module
import cellprofiler.preferences


log = logging.getLogger(__name__)


H_HEADER = 'Header'
H_VERSION_LEGACY = 'Version'
H_PIPELINE_VERSION = 'PipelineVersion'
H_CP_VERSION = 'CellProfilerVersion'

# The current pipeline file format version
CURRENT_PIPELINE_VERSION = 5

# The number of modules in the pipeline
H_MODULE_COUNT = "ModuleCount"

# The cookie that identifies a file as a CellProfiler pipeline
COOKIE_PREFIX = "CellProfiler Pipeline"
COOKIE_SUFFIX = "http://www.cellprofiler.org"

# Pipeline dimensionality
H_PIPELINE_DIMENSION = "Volumetric"

# Module list sentinal
H_MODULE_LIST = "Module List"

# Private module attributes
M_PRIVATE_ATTRIBUTES = "Private Module Attributes"
M_SETTINGS = "Module Settings"
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


# I actually want this to take in a pipeline object, which means that we'll have to have access to
# the modules list. It seems like this is available in pipeline.modules()
def save_yaml(modules, filename, modules_to_save=None, volumetric=False):
    # For readability (at least at first), we want the pipelien contents to be in a
    # certain order. Ultimately, everything but the per-module settings (see below)
    # can be in any order - they're accessed as a dictionary so it shouldn't matter.
    pipeline_dict = {
        COOKIE_PREFIX: COOKIE_SUFFIX,
        H_HEADER: {
            H_CP_VERSION: cellprofiler.__version__,
            H_PIPELINE_VERSION: CURRENT_PIPELINE_VERSION,
            H_PIPELINE_DIMENSION: volumetric,
            H_MODULE_COUNT: len(modules)
        },
        H_MODULE_LIST: []
    }

    attributes = (M_MODULE_NUMBER, M_SVN_VERSION, M_VARIABLE_REVISION,
                  M_SHOW_WINDOW, M_NOTES, M_ENABLED, M_WANTS_PAUSE)

    # For now, I'm going to try and get feature parity with the savetxt function
    for module in modules:
        if modules_to_save is not None and module.module_num not in modules_to_save:
            continue

        module_info = {
            # Not only is cellprofiler expecting some of these settings to be in
            # the same order, but some of the settings can be repeated multiple times.
            # Essentially, we can't use a dictionary here, so we have to use a list of
            # dictionaries. See below for further explanation.
            M_SETTINGS: [{setting.text: setting.unicode_value} for setting in module.settings()],

            # Private module attributes should be at the end
            M_PRIVATE_ATTRIBUTES: {attribute: getattr(module, attribute) for attribute in attributes}
        }

        # Note: it may seem weird that we're adding dictionaries with a single key to
        # a list. If our modules list was actually a dictionary, users wouldn't be able
        # to add more than one instance of a module to the pipeline file, since they key
        # is the module name and that key has to be unique.
        pipeline_dict[H_MODULE_LIST].append({module.module_name: module_info})

    with codecs.open(filename, "w", 'utf-8') as out_file:
        # Use safe_dump here because we don't want yaml putting in all these
        # !!python/unicode imperatives all over the place. Additionally, this makes
        # it significantly more readable.
        out_file.write(yaml.safe_dump(pipeline_dict, default_flow_style=False))


# TODO: I would actually like this to return a pipeline object that has everything set up
# TODO: For now we'll just return the modules, and the volumetric flag
def load_yaml(filename, raise_on_error=False):
    with codecs.open(filename, 'r', 'utf-8') as in_file:
        pipe_str = in_file.read()
    pipeline_dict = yaml.safe_load(pipe_str)

    if COOKIE_PREFIX not in pipeline_dict:
        # This isn't mission critical, we'll make that check below
        log.warning("Pipeline file {} may not be a valid CellProfiler pipeline".format(filename))

    is_headless = cellprofiler.preferences.get_headless()
    volumetric = False

    try:
        # Extract the header
        header = pipeline_dict[H_HEADER]
        # Check pipeline file version
        pipeline_version = int(header[H_PIPELINE_VERSION])

        # From the __future__
        if pipeline_version > CURRENT_PIPELINE_VERSION:
            raise PipelineLoadException(textwrap.dedent("""
                Pipeline file version is {}.
                CellProfiler can only read version {} or less.
                Please upgrade to the latest version of CellProfiler in order to use this pipeline.
            """.format(pipeline_version, CURRENT_PIPELINE_VERSION)
            ))
        # Anything that needs to be done for previous versions can go here

        # Compare the version of cellprofiler that was used to save the pipeline
        cp_version = distutils.version.StrictVersion(header[H_CP_VERSION])
        if cp_version < distutils.version.StrictVersion(cellprofiler.__version__) and not is_headless:
            log.warning(textwrap.dedent("""
                Your pipeline was saved using an old version of CellProfiler (version {}). 
                The current version of CellProfiler can load and run this pipeline, 
                but if you make changes to it and save, the older version of CellProfiler 
                (perhaps the version your collaborator has?) may not be able to load it.
                You can ignore this warning if you do not plan to save this pipeline or 
                if you will only use it with this or later versions of CellProfiler.
            """.format(cp_version)))

        # Check the pipeline dimensionality
        volumetric = header[H_PIPELINE_DIMENSION]

        # Get the module count
        module_count = header[H_MODULE_COUNT]

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
                # This import HAS to be here (and not at the top of the file) because
                # it may overwrite the other modules that have already been loaded
                from cellprofiler.modules import instantiate_module
                module = instantiate_module(module_name)

                # Extract the private attributes
                # This is just a dictionary
                private_attrs = module_info[M_PRIVATE_ATTRIBUTES]

                for attr_name, attr_value in private_attrs.items():
                    setattr(module, attr_name, attr_value)

                # Extract the settings
                # This is a list of dictionaries (to preserve order and counter uniqueness)
                # We need to decompose this to re-hydrate the module settings
                # E.g. [{'a': 1}, {'b': 2}, {'a': 4}] --> [1, 2, 4]
                module_settings = module_info[M_SETTINGS]
                module_settings = [value for setting in module_settings for value in setting.values()]

                # Set the module specific attributes
                module.set_settings_from_values(module_settings,
                                                private_attrs[M_VARIABLE_REVISION],
                                                module_name)

                # Finally, append and increment the module version number
                new_modules.append(module)
                module_number += 1

            except Exception as err:
                log.warning("Failed to load module {}-{}".format(module_name, module_number))
                if raise_on_error:
                    raise
                log.exception(err)
                log.warning("Continuing to load the rest of the pipeline")

        if module_count > len(new_modules):
            log.warning("{} modules could not be imported".format(module_count - len(new_modules)))

        return new_modules, volumetric

    except KeyError as err:
        log.error("Unable to load pipeline file {}".format(err))
        log.exception(err)
        raise PipelineLoadException(err)
