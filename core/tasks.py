from background_task import background

# generic imports 
import json
import math
import os
import polling
import time
import uuid

# Get an instance of a logger
import logging
logger = logging.getLogger(__name__)

from core import models as models

'''
This file provides background tasks that are performed with Django-Background-Tasks
'''

@background(schedule=1)
def delete_model_instance(instance_model, instance_id, verbose_name=uuid.uuid4().urn):

	'''
	Background task to delete generic DB model instance
	'''
	
	# try:

	# get model		
	m = getattr(models, instance_model, None)

	if m:

		# get model instance
		i = m.objects.get(pk=int(instance_id))
		logger.debug('retrieved %s model, instance ID %s, deleting' % (m.__name__, instance_id))
	
		# delete		
		return i.delete()

	else:
		logger.debug('Combine model %s not found, aborting' % (instance_model))	


@background(schedule=1)
def download_and_index_bulk_data(dbdd_id, verbose_name=uuid.uuid4().urn):

	'''
	Background task driver to manage downloading and indexing of bulk data

	Args:
		dbdd_id (int): ID of DPLABulkDataDownload (dbdd) instance
	'''

	# init bulk download instance
	dbdd = models.DPLABulkDataDownload.objects.get(pk=dbdd_id)

	# init data client with filepath
	dbdc = models.DPLABulkDataClient()

	# download data
	logger.debug('downloading %s' % dbdd.s3_key)
	dbdd.status = 'downloading'
	dbdd.save()
	download_results = dbdc.download_bulk_data(dbdd.s3_key, dbdd.filepath)	

	# index data
	logger.debug('indexing %s' % dbdd.filepath)
	dbdd.status = 'indexing'
	dbdd.save()
	es_index = dbdc.index_to_es(dbdd.s3_key, dbdd.filepath)	

	# update and return
	dbdd.es_index = es_index
	dbdd.status = 'finished'
	dbdd.save()



@background(schedule=1)
def create_validation_report(ct_id):

	'''
	Function to generate a Validation Report for a Job as a bg task

	Args:
		request (django.request): request object with parameters needed for report generation

	Returns:
		location on disk
	'''

	# get CombineTask (ct)
	ct = models.CombineBackgroundTask.objects.get(pk=int(ct_id))

	# get CombineJob
	cjob = models.CombineJob.get_combine_job(int(ct.task_params['job_id']))

	# run report generation
	report_output = cjob.generate_validation_report(
		report_format=ct.task_params['report_format'],
		validation_scenarios=ct.task_params['validation_scenarios'],
		mapped_field_include=ct.task_params['mapped_field_include']
	)
	logger.debug('validation report output: %s' % report_output)

	# save validation report output to Combine Task output
	ct.task_output_json = json.dumps({
		'report_format':ct.task_params['report_format'],		
		'report_output':report_output
	})
	ct.save()


@background(schedule=1)
def job_export_mapped_fields(ct_id):

	# get CombineTask (ct)
	ct = models.CombineBackgroundTask.objects.get(pk=int(ct_id))

	# get CombineJob
	cjob = models.CombineJob.get_combine_job(int(ct.task_params['job_id']))

	# set output filename
	export_output = '/tmp/job_%s_mapped_fields.csv' % cjob.job.id

	# issue es2csv as os command
	cmd = "es2csv -q '*' -i 'j%(job_id)s' -D 'record' -o '%(export_output)s'" % {
		'job_id':cjob.job.id,
		'export_output':export_output
	}

	# handle kibana style
	if ct.task_params['kibana_style']:
		cmd += ' -k'

	logger.debug(cmd)
	os.system(cmd)

	# save export output to Combine Task output
	ct.task_output_json = json.dumps({		
		'export_output':export_output,
		'name':export_output.split('/')[-1]
	})
	ct.save()


@background(schedule=1)
def job_export_documents(ct_id):

	'''
	- submit livy job and poll until complete
		- use livy session from cjob (works, but awkward way to get this)
	- add wrapper element to file parts
	- rename file parts
	- tar/zip together
	'''

	# get CombineTask (ct)
	try:
		ct = models.CombineBackgroundTask.objects.get(pk=int(ct_id))
		logger.debug('using %s' % ct)

		# get CombineJob
		cjob = models.CombineJob.get_combine_job(int(ct.task_params['job_id']))

		# generate spark code
		output_path = str(uuid.uuid4())

		spark_code = "import math,uuid\nfrom console import *\ndf = get_job_as_df(spark, %(job_id)d)\ndf.select('document').rdd.repartition(math.ceil(df.count()/%(records_per_file)d)).map(lambda row: row.document.replace('<?xml version=\"1.0\" encoding=\"UTF-8\"?>','')).saveAsTextFile('file:///tmp/%(output_path)s')" % {
			'job_id':cjob.job.id,
			'output_path':output_path,
			'records_per_file':ct.task_params['records_per_file']
		}
		logger.debug(spark_code)

		# submit to livy
		if cjob.livy_session.session_id:
			submit = models.LivyClient().submit_job(cjob.livy_session.session_id, {'code':spark_code})
		else:
			raise Exception('No Livy session found, cannot export records')

		# poll until complete
		def spark_job_done(response):
			return response['state'] == 'available'

		results = polling.poll(lambda: models.LivyClient().job_status(submit.headers['Location']).json(), check_success=spark_job_done, step=5, poll_forever=True)
		logger.debug(results)

		# wrap documents in root element

		# zip together as archive, save to output

		# save export output to Combine Task output
		ct.task_output_json = json.dumps({		
			'export_output':'/tmp/%s' % output_path,
			'name':'THIS WILL BE THE ARCHIVE FILE'
		})
		ct.save()

	except Exception as e:

		logger.debug(str(e))

		# attempt to capture error and return for task
		ct.task_output_json = json.dumps({		
			'error':str(e)
		})
		ct.save()



@background(schedule=1)
def test_bg_task(duration=5):

	logger.debug('preparing to sleep for: %s' % duration)
	time.sleep(duration)
	return "we had a good nap"











