"""
=======================
Module: bbcflib.c4seq
=======================

This module provides functions to run a 4c-seq analysis from reads mapped on
a reference genome.

"""

from bein import *
from bein.util import touch
from bbcflib import daflims, genrep, frontend, email, gdv, track, createlib
from bbcflib.mapseq import *
import sys, getopt, os, json, re
import gMiner as gm

grpId=1
step=0

#-------------------------------------------#
# Functions 
#-------------------------------------------#
# call script segToFrag.awk
@program
def segToFrag(in_countsPerFragFile,regToExclude=None, script_path='./'):
	''' 
		This function calls segToFrag.awk (which transforms the counts per segment to a normalised count per fragment) 
		Gives the region to exclude if any 
	'''
	if regToExclude == None:
		print('will call: awk -f '+script_path+'segToFrag.awk '+in_countsPerFragFile)
		return {'arguments': ["awk","-f",script_path+'segToFrag.awk',in_countsPerFragFile],
			'return_value':None}
	else:	
		print('will call: awk -f '+script_path+'segToFrag.awk '+' -v reg2Excl='+regToExclude+' '+in_countsPerFragFile)
		return {'arguments': ["awk","-f",script_path+'segToFrag.awk ',"-v","reg2Excl="+regToExclude,in_countsPerFragFile],
			'return_value':None}

def call_segToFrag(*args, **kwargs):
	filename = unique_filename_in()
        kwargs["stdout"] = filename
 	future=segToFrag.nonblocking(*args, **kwargs)
	future.wait()
        return filename

# *** parse the output of call_segToFrag
def parseSegToFrag(infile):
	''' Parse the output of segToFrag '''
	filename_all = unique_filename_in()
	out_all = open(filename_all,'w')
	filename = unique_filename_in()
	output = open(filename,'w')
	with open(infile,"r") as f:
		for s in f:
			s=s.strip('\n')
			if re.search(r'IsValid',s.split('\t')[2]) :
				coord=((s.split('\t')[1]).split(':')[1]).split('-')
				out_all.write((s.split('\t')[1]).split(':')[0]+'\t'+str(int(coord[0])-1)+'\t'+coord[1]+'\t'+s.split('\t')[11]+'\n')
				if float(s.split('\t')[11])>0.0:
					output.write((s.split('\t')[1]).split(':')[0]+'\t'+str(int(coord[0])-1)+'\t'+coord[1]+'\t'+s.split('\t')[11]+'\n')
	output.close()
	out_all.close()
	return [filename,filename_all]

# *** To sort a file on coordinates
@program
def sortOnCoord(infile):
	return{'arguments': ["sort","-k1,1","-k2,2n","-k3,3n",infile],
		'return_value':None }

def call_sortOnCoord(*args, **kwargs):
	filename = unique_filename_in()
        kwargs["stdout"] = filename
	future=sortOnCoord.nonblocking(*args, **kwargs)
	future.wait()
	return filename


# *** Create a dictionary with infos for each primer (from file primers.fa)
# ex: primers_dict=loadPrimers('/archive/epfl/bbcf/data/DubouleDaan/finalAnalysis/XmNGdlXjqoj6BN8Rj2Tl/primers.fa')
def loadPrimers(primersFile):
	'''
		Create a dictionary with infos for each primer (from file primers.fa) 
	'''
	primers={}
	with open(primersFile,'r') as f:
		for s in f.readlines():
			s=s.strip('\n')
			if re.search(r'^>',s):
				primerInfos={}
				infos=s.split('|')
				n=len(infos)-1
				name=infos[0][1:len(infos[0])]
				primerInfos['fullseq']=infos[1]
				primerInfos['baitcoord']=infos[2]
				primerInfos['primary']=infos[3]
				if re.search('Exclude',infos[len(infos)-1]):
					n=n-1
					primerInfos['regToExclude']=(infos[len(infos)-1]).split('=')[1]
                                        print "primerInfos['regToExclude']: " + primerInfos['regToExclude']
				primerInfos['seqToFilter']=infos[4:n]
				if not name in primers:	
					primers[name]=primerInfos
					prevPrimer=name
			else:
				primers[name]['seq']=s
	return primers


@program
def profileCorrection(inputFile,baitCoord,name,outputFile,reportFile,script_path='./'):
	return{'arguments': ["R","--vanilla","--no-restore","--slave","-f",script_path+"profileCorrection.R","--args",inputFile,baitCoord,name,outputFile,reportFile],
                'return_value':None}

@program
def smoothFragFile(inputFile,nFragsPerWin,curName,outputFile,regToExclude=None,script_path='./'):
        if not(regToExclude): regToExclude=''
	return{'arguments': ["R","--vanilla","--no-restore","--slave","-f",script_path+"smoothData.R","--args",inputFile,nFragsPerWin,curName,outputFile,regToExclude],
        	'return_value':None}

# *** main function to compute normalised counts per fragments from a density file
# ex: resfiles=density_to_countsPerFrag(ex,mapped_files[gid][rid]['wig']['merged'],mapped_files[gid][rid]['libname'],assembly.name,reffile,regToExclude,working_dir, script_path, 'lsf')
def density_to_countsPerFrag(ex,density_file,density_name,assembly_name,reffile,regToExclude,wd,script_path, via='lsf'):
	'''
		main function to compute normalised counts per fragments from a density file 
	'''
	global grpId
	global step

	print("will call mean_score_by_feature for t1="+density_file+"(name="+density_name+") and t2="+reffile)
#	outdir=unique_filename_in()
#	os.mkdir(outdir)
#        touch(ex,wd+outdir)
        #ok: res=gm.run(track1=density_file,track1_name=density_name,track2=reffile,track2_name='libFile',track2_chrfile=assembly.name,operation_type='genomic_manip',manipulation='mean_score_by_feature',output_location=wd,output_name=outdir)
	
#	gMiner_job = { 'track1': density_file,
#                       'track1_name':density_name,
#                       'track2':reffile,
#                       'track2_name':'libFile',
#                       'track2_chrfile':assembly_name,
#                       'operation_type':'genomic_manip',
#                       'manipulation':'mean_score_by_feature',
#                       'output_location':outdir
#                       }
        output = unique_filename_in()
        from gMiner.operations.genomic_manip.scores import mean_score_by_feature
        with track.Track(density_file) as scores:
                with track.Track(reffile) as features:
                        with track.new(output,format='sql',chrmeta=assembly_name) as out:
                                for ch in scores:
                                        out.write(ch,mean_score_by_feature()(
                                                        scores.read(ch),
                                                        features.read(ch,fields=['start', 'end', 'name'])),
                                                  fields=['start', 'end', 'name', 'score'])

        ex.add(output,description=set_file_descr("meanScorePerFeature_"+density_name+".sql",groupId=grpId,step=step,type="sql",view="admin"))
     #  'output_location':wd,
#	print(gMiner_job)

	# calculate mean score per segments (via gFeatMiner)
#	res = run_gMiner.nonblocking(ex,gMiner_job,via=via).wait()
#	resfilename = unique_filename_in()
#	touch(ex,resfilename)
#	print("res filename="+resfilename)
##	ex.add(resfilename, description="none:meanScorePerFeature_"+density_name+".sql (template) [group"+str(grpId)+",step:"+str(step)+",type:template,view:admin]")
#	ex.add(res[0],description=set_file_descr("meanScorePerFeature_"+density_name+".sql",groupId=grpId,step=step,type="sql",view="admin"))
#	ex.add(res[0],description="sql:meanScorePerFeature_"+density_name+".sql [group:"+str(grpId)+",step:"+str(step)+",type:sql,view:admin]")
 ##                       associate_to_filename=resfilename, template='%s'+'.sql')

	countsPerFragFile=unique_filename_in()+".bed"
	with track.load(output,'sql') as t:
		t.convert(countsPerFragFile,'bed')
##	ex.add(countsPerFragFile,description="none:bed:meanScorePerFeature_"+density_name+".bed (template) [group:"+str(grpId)+",step:"+str(step)+",type:template,view:admin]")
	ex.add(countsPerFragFile,description=set_file_descr("meanScorePerFeature_"+density_name+".bed",groupId=grpId,step=step,type="bed"))
#	ex.add(countsPerFragFile+".bed",description="bed:meanScorePerFeature_"+density_name+".bed [group:"+str(grpId)+",step:"+str(step)+",type:bed]")
##			associate_to_filename=countsPerFragFile, template="%s"+".bed")
	step += 1

	# calculate normalised score per fragments (segToFrag)
	res = call_segToFrag(ex, countsPerFragFile, regToExclude, script_path, via=via)
	ex.add(res,description=set_file_descr("res_segToFrag_"+density_name+".bedGraph",groupId=grpId,step=step,type="bedGraph",view="admin",comment="rough"))
#	ex.add(res,description="none:res_segToFrag_"+density_name+" (rough) [group:"+str(grpId)+",step:"+str(step)+",type:bedGraph,view:admin]")
	[resBedGraph,resBedGraph_all]=parseSegToFrag(res)
	ex.add(resBedGraph,description=set_file_descr("res_segToFrag_"+density_name+".bedGraph",groupId=grpId,step=step,type="bedGraph",view="admin",comment="bedGraph non-sorted"))
	ex.add(resBedGraph_all,description=set_file_descr("res_segToFrag_"+density_name+"_all_nonSorted.bedGraph",groupId=grpId,step=step,type="bedGraph",view="admin",comment="all informative frags - null included - bedGraph non-sorted"))
	resBedGraph_all=call_sortOnCoord(ex,resBedGraph_all,via=via)
	ex.add(resBedGraph_all,description=set_file_descr("res_segToFrag_"+density_name+"_all.bedGraph",groupId=grpId,step=step,type="bedGraph",view="admin",comment="all informative frags - null included -sorted bedGraph"))
#	ex.add(resBedGraph,description="none:res_segToFrag_"+density_name+" (bedGraph non-sorted) [group:"+str(grpId)+",step:"+str(step)+"type:bedGraph,view:admin]")
	resBedGraph=call_sortOnCoord(ex,resBedGraph,via=via)
	headerFile=unique_filename_in();
	hfile=open(headerFile,'w')
	hfile.write('track type="bedGraph" name="'+density_name+' normalised counts per valid fragments" description="'+density_name+' normalised counts per valid fragments" visibility=full windowingFunction=maximum autoScale=off viewLimits=1:2000\n')
	hfile.close()
	sortedBedGraph=cat([headerFile,resBedGraph])
##	ex.add(sortedBedGraph,description="none:res_segToFrag"+denstiy_name+" (template) [group:"+str(grpId)+",step:"+str(step)+",type:template,view:admin]")
	ex.add(sortedBedGraph,description=set_file_descr("res_segToFrag_"+density_name+".bedGraph",groupId=grpId,step=step,type="bedGraph",comment="bedGraph sorted",uscc='1'))
#	ex.add(sortedBedGraph+".bedGraph",description="bedgraph:res_segToFrag_"+density_name+" (bedGraph sorted) [group:"+str(grpId)+",step:"+str(step)+",type:bedGraph]")
#			associate_to_filename=sortedBedGraph, template="%s"+".bedGraph")	
	sortedBedGraph_sql=unique_filename_in()
	touch(ex,sortedBedGraph_sql)
	with track.load(sortedBedGraph,'bedGraph', chrmeta=assembly_name) as t:
                t.convert(sortedBedGraph_sql+".sql",'sql')
#	#ex.add(sortedBedGraph_sql,description="sql:res_segToFrag_"+density_name+" (bedGraph sorted)")
##	ex.add(sortedBedGraph_sql,description="none:res_segToFrag_"+density_name+".sql (template) [group:"+str(grpId)+"step:"+str(step)+",type:template,view:admin]")
	ex.add(sortedBedGraph_sql+".sql",description=set_file_descr("res_segToFrag_"+density_name+".sql",groupId=grpId,step=step,type="sql",view="admin",comment="bedGraph sorted"))
#	ex.add(sortedBedGraph_sql+".sql",description="sql:res_segToFrag_"+density_name+".sql (bedGraph sorted) [group:"+str(grpId)+"step:"+str(step)+",type:sql,view:admin]")
 ##                       associate_to_filename=sortedBedGraph_sql, template='%s'+'.sql')
	step += 1
	return [output,countsPerFragFile,res,resBedGraph,sortedBedGraph,sortedBedGraph_sql]

# Main 
#-------------------------------------------#
# *** open the 4c-seq minilims and create execution
# *** 0.get/create the library 
# *** 1.when necessary, calculate the density file from the bam file (mapseq.parallel_density_sql)
# ### 2.calculate the count per fragment for each denstiy file with gFeatMiner:mean_score_by_feature to calculate)
def workflow_groups(ex, job, primers_dict, g_rep, mapseq_files, mapseq_url, script_path='', via='lsf' ):
	'''
		# Main 
		#-------------------------------------------#
		# *** open the 4C-seq minilims and create execution
		# *** 0.get/create the library 
		# *** 1.when necessary, calculate the density file from the bam file (mapseq.parallel_density_sql)
		# ### 2.calculate the count per fragment for each denstiy file with gFeatMiner:mean_score_by_feature to calculate)
	'''
	global grpId
	global step
	assembly = g_rep.assembly(job.assembly_id)
	processed={
		'lib' : {},
		'density' : {},
		'4cseq' : {}
		}
	
        job_groups=job.groups
	htss_mapseq = frontend.Frontend( url=mapseq_url )

	new_libs=[]
        fasta_allchr=assembly
        #fasta_allchr='/archive/epfl/bbcf/mleleu/pipeline_vMarion/pipeline_3Cseq/vWebServer_Bein/tests/test.minilims.files/8LkjoeWBoRw0mh1rLz8V' #for test: will be /scratch/cluster/monthly/htsstation/4cseq/job.id

	for gid, group in job_groups.iteritems():
		reffile=createlib.get_libForGrp(ex,group,fasta_allchr,new_libs, job.id, g_rep)
#		reffile='/archive/epfl/bbcf/data/DubouleDaan/library_Nla_30bps/library_Nla_30bps_segmentInfos.bed'
		processed['lib'][gid]=reffile
		#ex.add(reffile,description=set_file_descr("library.bed",group=group['name'],step=step,type="bed"))	
#		ex.add(reffile,description="bed:library [group:"+str(grpId)+",step:"+str(step)+",type:bed]")

		for rid,run in group['runs'].iteritems():
                        #job_mapseq=htss_mapseq.job(run['key'])
		
			if 'regToExclude' in primers_dict[mapseq_files[gid][rid]['libname']]:
                                regToExclude=primers_dict[mapseq_files[gid][rid]['libname']]['regToExclude']
			else:
			        regToExclude=None
			print("regToExclude="+str(regToExclude))
                        if not job.options.get('compute_densities') or job.options.get('merge_strands') != 0:
				print("will call parallel_density_sql with bam:"+mapseq_files[gid][rid]['bam']+"\n")
				density_file=parallel_density_sql( ex, mapseq_files[gid][rid]['bam'],
                        						assembly.chromosomes,
                        			                        nreads=mapseq_files[gid][rid]['stats']["total"],
                                                 			merge=0,
                                                 			convert=False,
                                                 			via=via )
				mapseq_files[gid][rid]['wig']['merged']=density_file+"merged.sql"
				print("name of density_file after parallel_density_sql="+density_file)
				print("density file:"+mapseq_files[gid][rid]['wig']['merged'])
                        else:
                                print("Will use existing density file:"+mapseq_files[gid][rid]['wig']['merged'])

			print("density files:")
			print(mapseq_files[gid][rid]['wig']['merged'])
			print("Will convert density file .sql to .wig")
			mapseq_wig = unique_filename_in()
			touch(ex,mapseq_wig)
			print("mapseq_wig filename will be:"+mapseq_wig)
			with track.load(mapseq_files[gid][rid]['wig']['merged'],'sql') as t:
                		t.convert(mapseq_wig+".wig",'wig')
##			ex.add(mapseq_wig,description="none:density_file_"+mapseq_files[gid][rid]['libname']+".wig (template) [group:"+str(grpId)+",step:"+str(step)+",type:template,view:admin]")
			ex.add(mapseq_wig+".wig",description=set_file_descr("density_file_"+mapseq_files[gid][rid]['libname']+".wig",group=group['name'],step=step,type="wig",ucsc='1'))	
#			ex.add(mapseq_wig+".wig",description="wig:density_file_"+mapseq_files[gid][rid]['libname']+".wig [group:"+str(grpId)+",step:"+str(step)+",type:wig]")
##				associate_to_filename=mapseq_wig, template="%s"+".wig")

			ex.add(mapseq_files[gid][rid]['wig']['merged'],description=set_file_descr("density_file_"+mapseq_files[gid][rid]['libname']+".sql",group=group['name'],step=step,type="sql"))
#		        ex.add(mapseq_files[gid][rid]['wig']['merged'],description="sql:density_file_"+mapseq_files[gid][rid]['libname']+" [group:"+str(grpId)+",step:"+str(step)+",type:sql]"  )
 #                       #ex.add(mapseq_files[gid][rid]['wig']['merged'],description='none:density_file_'+mapseq_files[gid][rid]['libname']+'.sql (template)')
 #                       #ex.add(mapseq_files[gid][rid]['wig']['merged']+".sql",description='sql:density_file_'+mapseq_files[gid][rid]['libname']+'.sql (sql density file)', 
 #                       #        associate_to_filename=mapseq_files[gid][rid]['wig']['merged'], template='%s'+'.sql')	
                        processed['density'][mapseq_files[gid][rid]['libname']]=mapseq_files[gid][rid]['wig']['merged']

			print("Will process to the main part of 4cseq module: calculate normalised counts per fragments from density file:"+mapseq_files[gid][rid]['wig']['merged'])
			resfiles=density_to_countsPerFrag(ex,mapseq_files[gid][rid]['wig']['merged'],mapseq_files[gid][rid]['libname'],assembly.name,reffile,regToExclude,ex.remote_working_directory+'/',script_path, via)
			processed['4cseq']=resfiles
			
			print("Will proceed to profile correction of file "+str(resfiles[4]))
			profileCorrectedFile=unique_filename_in()
			reportFile_profileCorrection=unique_filename_in()
			profileCorrection.nonblocking(ex,resfiles[4],primers_dict[mapseq_files[gid][rid]['libname']]['baitcoord'],mapseq_files[gid][rid]['libname'],profileCorrectedFile,reportFile_profileCorrection,script_path,via=via).wait()
		        ex.add(profileCorrectedFile,description=set_file_descr("res_segToFrag_"+mapseq_files[gid][rid]['libname']+"_profileCorrected.bedGraph",group=group['name'],step=step,type="bedGraph",comment="profile corrected data;bedGraph sorted",ucsc='1'))
			ex.add(reportFile_profileCorrection,description=set_file_descr("report_profileCorrection_"+mapseq_files[gid][rid]['libname']+".pdf",group=group['name'],step=step,type="pdf",comment="report profile correction"))
			step += 1
	
			print("Will smooth data before and after profile correction")
			#call_smoothData(resfiles[4],nFragsPerWin)
        		nFragsPerWin=str(10)
        		outputfile=unique_filename_in()
		        smoothFragFile(ex,resfiles[4],nFragsPerWin,mapseq_files[gid][rid]['libname'],outputfile,regToExclude,script_path)
			ex.add(outputfile,description=set_file_descr("res_segToFrag_"+mapseq_files[gid][rid]['libname']+"_smoothed_"+nFragsPerWin+"FragsPerWin.bedGraph",group=group['name'],step=step,type="bedGraph",comment="smoothed data, before profile correction",ucsc='1'))
			
        		outputfile_afterProfileCorrection=unique_filename_in()
		        smoothFragFile(ex,profileCorrectedFile,nFragsPerWin,mapseq_files[gid][rid]['libname'],outputfile_afterProfileCorrection,regToExclude,script_path)
			ex.add(outputfile_afterProfileCorrection,description=set_file_descr("res_segToFrag_"+mapseq_files[gid][rid]['libname']+"_profileCorrected_smoothed_"+nFragsPerWin+"FragsPerWin.bedGraph",group=grpId,step=step,type="bedGraph",comment="smoothed data, after profile correction",ucsc='1'))
		grpId += 1
		step=0
	return processed

