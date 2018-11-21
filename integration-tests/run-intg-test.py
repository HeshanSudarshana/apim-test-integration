# Copyright (c) 2018, WSO2 Inc. (http://wso2.com) All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# importing required modules
import sys
from xml.etree import ElementTree as ET
import subprocess
import wget
import logging
import inspect
import os
import shutil
import pymysql
import sqlparse
import glob
import stat
import re
from pathlib import Path
import urllib.request as urllib2
from xml.dom import minidom
from subprocess import Popen, PIPE
import intg_test_manager as cm

from prod_test_constant import DB_META_DATA, ARTIFACT_REPORTS_PATHS, DIST_POM_PATH, LIB_PATH, M2_PATH, \
    DISTRIBUTION_PATH, DATASOURCE_PATHS, POM_FILE_PATHS, INTEGRATION_PATH, TESTNG_DIST_XML_PATH, \
    TESTNG_SERVER_MGT_DIST

from intg_test_constant import NS, ZIP_FILE_EXTENSION, CARBON_NAME, VALUE_TAG, SURFACE_PLUGIN_ARTIFACT_ID, \
    DEPLOYMENT_PROPERTY_FILE_NAME, LOG_FILE_NAME, PRODUCT_STORAGE_DIR_NAME, \
    DEFAULT_DB_USERNAME, LOG_STORAGE, TEST_OUTPUT_DIR_NAME, DEFAULT_ORACLE_SID, MYSQL_DB_ENGINE, \
    ORACLE_DB_ENGINE, PRODUCT_STORAGE_DIR_NAME, MSSQL_DB_ENGINE, WSO2SERVER


database_names = []
db_engine = None
sql_driver_location = None


def get_db_meta_data(argument):
    switcher = DB_META_DATA
    return switcher.get(argument, False)


def modify_datasources():
    """Modify datasources files which are defined in the const.py. DB ulr, uname, pwd, driver class values are modifying.
    """
    for data_source in datasource_paths:
        file_path = Path(storage_dist_abs_path / data_source)
        if sys.platform.startswith('win'):
            file_path = cm.winapi_path(file_path)
        logger.info("Modifying datasource: " + str(file_path))
        artifact_tree = ET.parse(file_path)
        artifarc_root = artifact_tree.getroot()
        data_sources = artifarc_root.find('datasources')
        for item in data_sources.findall('datasource'):
            database_name = None
            for child in item:
                if child.tag == 'name':
                    database_name = child.text
                # special checking for namespace object content:media
                if child.tag == 'definition' and database_name:
                    configuration = child.find('configuration')
                    url = configuration.find('url')
                    user = configuration.find('username')
                    password = configuration.find('password')
                    validation_query = configuration.find('validationQuery')
                    drive_class_name = configuration.find('driverClassName')
                    if MYSQL_DB_ENGINE == cm.database_config['db_engine'].upper():
                        url.text = url.text.replace(url.text, cm.database_config[
                            'url'] + "/" + database_name + "?autoReconnect=true&useSSL=false&requireSSL=false&"
                                                           "verifyServerCertificate=false")
                        user.text = user.text.replace(user.text, cm.database_config['user'])
                    elif ORACLE_DB_ENGINE == cm.database_config['db_engine'].upper():
                        url.text = url.text.replace(url.text, cm.database_config['url'] + "/" + DEFAULT_ORACLE_SID)
                        user.text = user.text.replace(user.text, database_name)
                        validation_query.text = validation_query.text.replace(validation_query.text,
                                                                              "SELECT 1 FROM DUAL")
                    elif MSSQL_DB_ENGINE == cm.database_config['db_engine'].upper():
                        url.text = url.text.replace(url.text,
                                                    cm.database_config['url'] + ";" + "databaseName=" + database_name)
                        user.text = user.text.replace(user.text, cm.database_config['user'])
                    else:
                        url.text = url.text.replace(url.text, cm.database_config['url'] + "/" + database_name)
                        user.text = user.text.replace(user.text, cm.database_config['user'])
                    password.text = password.text.replace(password.text, cm.database_config['password'])
                    drive_class_name.text = drive_class_name.text.replace(drive_class_name.text,
                                                                          cm.database_config['driver_class_name'])
                    database_names.append(database_name)
        artifact_tree.write(file_path)


def configure_product():
    try:
        global datasource_paths
        global target_dir_abs_path
        global storage_dist_abs_path
        global storage_dir_abs_path

        datasource_paths = DATASOURCE_PATHS
        zip_name = dist_name + ZIP_FILE_EXTENSION

        storage_dir_abs_path = Path(cm.workspace + "/" + PRODUCT_STORAGE_DIR_NAME)
        target_dir_abs_path = Path(cm.workspace + "/" + cm.product_id + "/" + DISTRIBUTION_PATH)
        storage_zip_abs_path = Path(storage_dir_abs_path / zip_name)
        storage_dist_abs_path = Path(storage_dir_abs_path / dist_name)
        configured_dist_storing_loc = Path(target_dir_abs_path / dist_name)
        script_name = Path(WSO2SERVER)

        script_path = Path(storage_dist_abs_path / script_name)

        cm.extract_product(storage_dir_abs_path, storage_zip_abs_path)
        cm.attach_jolokia_agent(script_path)
        cm.copy_jar_file(Path(cm.database_config['sql_driver_location']), Path(storage_dist_abs_path / LIB_PATH))

        if datasource_paths is not None:
            modify_datasources()
        else:
            logger.info("datasource paths are not defined in the config file")
        os.remove(str(storage_zip_abs_path))
        cm.compress_distribution(configured_dist_storing_loc, storage_dir_abs_path)
        cm.add_distribution_to_m2(storage_dir_abs_path, M2_PATH)
        shutil.rmtree(configured_dist_storing_loc, onerror=cm.on_rm_error)
        return database_names
    except FileNotFoundError as e:
        logger.error("Error occurred while finding files", exc_info=True)
    except IOError as e:
        logger.error("Error occurred while accessing files", exc_info=True)
    except Exception as e:
        logger.error("Error occurred while configuring the product", exc_info=True)


# Since we have added a method to clone a given git branch and checkout to the latest released tag it is not required to
# modify pom files. Hence in the current implementation this method is not using.
# However, in order to execute this method you can define pom file paths in const_<prod>.py as a constant
# and import it to run-intg-test.py. Thereafter assign it to global variable called pom_file_paths in the
# configure_product method and call the modify_pom_files method.
def modify_pom_files():
    for pom in POM_FILE_PATHS:
        file_path = Path(cm.workspace + "/" + cm.product_id + "/" + pom)
        if sys.platform.startswith('win'):
            file_path = cm.winapi_path(file_path)
        logger.info("Modifying pom file: " + str(file_path))
        ET.register_namespace('', NS['d'])
        artifact_tree = ET.parse(file_path)
        artifarct_root = artifact_tree.getroot()
        data_sources = artifarct_root.find('d:build', NS)
        plugins = data_sources.find('d:plugins', NS)
        for plugin in plugins.findall('d:plugin', NS):
            artifact_id = plugin.find('d:artifactId', NS)
            if artifact_id is not None and artifact_id.text == SURFACE_PLUGIN_ARTIFACT_ID:
                configuration = plugin.find('d:configuration', NS)
                system_properties = configuration.find('d:systemProperties', NS)
                for neighbor in system_properties.iter('{' + NS['d'] + '}' + CARBON_NAME):
                    neighbor.text = cm.modify_distribution_name(neighbor)
                for prop in system_properties:
                    name = prop.find('d:name', NS)
                    if name is not None and name.text == CARBON_NAME:
                        for data in prop:
                            if data.tag == VALUE_TAG:
                                data.text = cm.modify_distribution_name(data)
                break
        artifact_tree.write(file_path)


def main():
    try:
        global logger
        global dist_name
        logger = cm.function_logger(logging.DEBUG, logging.DEBUG)
        if sys.version_info < (3, 6):
            raise Exception(
                "To run run-intg-test.py script you must have Python 3.6 or latest. Current version info: " + sys.version_info)
        cm.read_property_files()
        if not cm.validate_property_readings():
            raise Exception(
                "Property file doesn't have mandatory key-value pair. Please verify the content of the property file "
                "and the format")

        # get properties assigned to local variables
        pom_path = DIST_POM_PATH
        engine = cm.db_engine.upper()
        db_meta_data = get_db_meta_data(engine)
        distribution_path = DISTRIBUTION_PATH
        artifact_report_paths = ARTIFACT_REPORTS_PATHS
        testng_dest = TESTNG_DIST_XML_PATH
        testng_svr_mgt_dest = TESTNG_SERVER_MGT_DIST

        # construct database configuration
        cm.construct_db_config(db_meta_data)
        # clone the repository
        cm.clone_repo()
        # set the custom testng.xml or the product testng.xml
        cm.set_custom_testng(testng_dest, testng_svr_mgt_dest)

        if cm.test_mode == "WUM":
            dist_name = cm.get_dist_name_wum()

        elif cm.test_mode == "RELEASE":
            cm.checkout_to_tag()
            dist_name = cm.get_dist_name(pom_path)
            cm.get_latest_released_dist()
        elif cm.test_mode == "SNAPSHOT":
            dist_name = cm.get_dist_name(pom_path)
            # build the distribution for snapshot test mode
            cm.build_snapshot_dist(distribution_path)

        db_names = configure_product()
        if db_names is None or not db_names:
            raise Exception("Failed the product configuring")

        cm.setup_databases(db_names, db_meta_data)
        if cm.product_id == "product-apim":
            module_path = Path(cm.workspace + "/" + cm.product_id + "/" + 'modules/api-import-export')
            cm.build_module(module_path)
        intg_module_path = Path(cm.workspace + "/" + cm.product_id + "/" + INTEGRATION_PATH)
        cm.build_module(intg_module_path)
        cm.save_test_output(artifact_report_paths)
        cm.create_output_property_fle()
    except Exception as e:
        logger.error("Error occurred while running the run-intg.py script", exc_info=True)
    except BaseException as e:
        logger.error("Error occurred while doing the configuration", exc_info=True)


if __name__ == "__main__":
    main()
