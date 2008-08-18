import os
import shutil
import tempfile
from optparse import make_option
from django.core.management.base import BaseCommand
from django.conf import settings
from django.template import Context, Template

# TODO: The (ab)use of __file__ makes me nervous. Should improve compatibility
#       with zipimport.
#
#       Also, I'd like to move application.py out of the WAR root. Need to check
#       if modjy can support a path relative to the war root to specify the
#       location of application.py.

class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--include-java-libs', dest='include_java_libs', default='',
                    help='Comma separated list of java libraries (JAR files) to '
                         'include. Typically used for JDBC drivers '),
        make_option('--include-py-libs', dest='include_py_libs', default='',
                    help='Comma separated list of python libraries (directories '
                         'or JAR/ZIP files) to include'),
        make_option('--context-root', dest='context_root', default='',
                    help='Name of the context root for the application. If '
                         'unspecified, the project name is used. The context '
                          'root name is used as the name of the WAR file, and '
                          'as a prefix for some url-related settings, such as '
                          'MEDIA_URL')
    )
    help = ("Builds a WAR file for stand-alone deployment on a Java "
            "Servlet container")
    def handle(self, *args, **options):
        project_name = self.project_name()
        context_root = options['context_root'] or project_name
        exploded_war_dir = os.path.join(tempfile.mkdtemp(), project_name)
        print
        print "Assembling WAR on %s" % exploded_war_dir
        print
        self.copy_skel(exploded_war_dir)
        self.fill_templates(exploded_war_dir,
                            ['WEB-INF/web.xml', 'application.py'],
                            {'project_name': project_name,
                             'settings': settings})
        self.copy_jython(exploded_war_dir)
        self.copy_django(exploded_war_dir)
        self.copy_admin_media(exploded_war_dir)
        self.copy_project(exploded_war_dir)
        self.fix_project_settings(exploded_war_dir, context_root)
        self.copy_project_media(exploded_war_dir)
        self.copy_apps(exploded_war_dir)
        if options['include_java_libs']:
            for java_lib in options['include_java_libs'].split(','):
                self.copy_java_lib(exploded_war_dir, java_lib)
        if options['include_py_libs']:
            for py_lib in options['inclide_py_libs'].split(','):
                self.copy_py_lib(exploded_war_dir, py_lib)
        print "Finished."

    def copy_skel(self, exploded_war_dir):
        print "Copying WAR skeleton..."
        shutil.copytree(self._skel_directory(), exploded_war_dir)

    def _skel_directory(self):
        return os.path.join(os.path.dirname(__file__), 'war_skel')

    def fill_templates(self, exploded_war_dir, relative_file_names, vars):
        for relative_file_name in relative_file_names:
            file_name = os.path.join(*[exploded_war_dir] +
                                     relative_file_name.split('/'))
            template = Template(file(file_name).read())
            file(file_name, 'w').write(template.render(Context(vars)))

    def copy_jython(self, exploded_war_dir):
        jython_lib_path = os.path.dirname(os.path.abspath(os.__file__))
        jython_home = os.path.dirname(jython_lib_path)
        if jython_home.endswith('.jar'):
            # We are on a Jython stand-alone installation.
            self.copy_java_lib(exploded_war_dir, jython_home)
        else:
            # Standard installation: jython.jar inside jython_home
            self.copy_java_lib(exploded_war_dir,
                               os.path.join(jython_home, 'jython.jar'))
            # XXX: Right now (August 2008), on the asm branch in subversion,
            # jython.jar depends on a javalib/jarjar.jar file, containing the
            # runtime dependencies. In the future this step may not be needed
            self.copy_java_lib(exploded_war_dir,
                               os.path.join(jython_home, 'javalib', 'jarjar.jar'))
            self.copy_py_lib(exploded_war_dir, jython_lib_path)

    def copy_django(self, exploded_war_dir):
        import django
        django_dir = os.path.dirname(os.path.abspath(django.__file__))
        self.copy_py_lib(exploded_war_dir, django_dir)

    def copy_admin_media(self, exploded_war_dir):
        from django.contrib import admin
        self.copy_media(exploded_war_dir,
                        os.path.join(os.path.dirname(admin.__file__), 'media'),
                        os.path.join(*settings.ADMIN_MEDIA_PREFIX.split('/')))

    def copy_project(self, exploded_war_dir):
        self.copy_py_lib(exploded_war_dir, self.project_directory())

    def fix_project_settings(self, exploded_war_dir, context_root):
        fix_media = (settings.MEDIA_URL and
                     not settings.MEDIA_URL.startswith('http'))
        fix_admin_media =  (settings.ADMIN_MEDIA_PREFIX and
                            not settings.ADMIN_MEDIA_PREFIX.startswith('http'))
        if not fix_media and not fix_admin_media:
            return

        fix = """
# Added by django-jython. Fixes URL prefixes to include the context root:
"""
        if fix_media:
            fix += "MEDIA_URL='/%s%s'\n" % (context_root, settings.MEDIA_URL)
        if fix_admin_media:
            fix += "ADMIN_MEDIA_PREFIX='/%s%s'\n" % (context_root,
                                                     settings.ADMIN_MEDIA_PREFIX)

        settings_name = settings.SETTINGS_MODULE.split('.')[-1]
        deployed_settings = os.path.join(exploded_war_dir,'WEB-INF', 'lib-python',
                                         self.project_name(), self.project_name(),
                                         settings_name + '.py')
        if os.path.exists(deployed_settings):
            settings_file_modified = file(deployed_settings, 'a')
            settings_file_modified.write(fix)
            settings_file_modified.close()
        else:
            print """WARNING: settings module file not found inside the project
directory (maybe you have split settings into a package?)

You SHOULD manually prefix the ADMIN_MEDIA_PREFIX and/or MEDIA_URL settings on the
deployed settings file. You can append the following block at the end of the file:

# ---------------------------- Begin Snip ---------------------------------
%s
# ----------------------------- End Snip -----------------------------------
""" % fix


    def copy_project_media(self, exploded_war_dir):
        if not settings.MEDIA_ROOT:
            print ("WARNING: Not copying project media, since MEDIA_ROOT "
                   "is not defined")
            return
        if not settings.MEDIA_URL:
            print ("WARNING: Not copying project media, since MEDIA_URL "
                   "is not defined")
            return
        if settings.MEDIA_URL.startswith('http'):
            print ("WARNING: Not copying project media, since MEDIA_URL "
                   "is absolute (starts with 'http')")
        self.copy_media(exploded_war_dir,
                        settings.MEDIA_ROOT,
                        os.path.join(*settings.MEDIA_URL.split('/')))

    def copy_apps(self, exploded_war_dir):
        for app in settings.INSTALLED_APPS:
            if app.startswith('django.') or \
                   app.startswith(self.project_name() + '.'):
                continue # Already included
            app_first_dir = os.path.dirname(os.path.abspath(__import__(app).__file__))
            self.copy_py_lib(exploded_war_dir, app_first_dir)

    def copy_java_lib(self, exploded_war_dir, java_lib):
        # java_lib is a path to a JAR file
        dest_name = os.path.basename(java_lib)
        print "Copying %s..." % dest_name
        shutil.copy(java_lib,
                    os.path.join(exploded_war_dir,
                                 'WEB-INF', 'lib', dest_name))

    def copy_py_lib(self, exploded_war_dir, py_lib_dir):
        dest_name = os.path.basename(py_lib_dir)
        print "Copying %s..." % dest_name
        if dest_name != 'Lib':
            # Each python library goes into its own sys.path entry (Except Lib,
            # which is itself a sys.path entry. Maybe I should add some flag to
            # this method instead of special-casing Lib)
            os.mkdir(os.path.join(exploded_war_dir,
                                  'WEB-INF', 'lib-python', dest_name))
            dest_name = os.path.join(dest_name, dest_name)

        shutil.copytree(py_lib_dir,
                        os.path.join(exploded_war_dir,
                                     'WEB-INF', 'lib-python', dest_name))

    def copy_media(self, exploded_war_dir, src_dir, dest_relative_path):
        if dest_relative_path[-1] == '/':
            dest_relative_path = dest_relative_path[:-1]
        if os.path.sep in dest_relative_path:
            # We have to construct the directory hierarchy (without the last
            # level)
            d = exploded_war_dir
            for sub_dir in os.path.split(dest_relative_path)[:-1]:
                d = os.path.join(d, sub_dir)
                os.mkdir(d)
        print "Copying %s..." % dest_relative_path
        shutil.copytree(src_dir,
                        os.path.join(exploded_war_dir, dest_relative_path))


    def settings_module(self):
        return __import__(settings.SETTINGS_MODULE, {}, {},
                          (settings.SETTINGS_MODULE.split(".")[-1],))
    def project_directory(self):
        return os.path.dirname(self.settings_module().__file__)

    def project_name(self):
        return os.path.basename(self.project_directory())
