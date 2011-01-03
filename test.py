from bbcflib import *
from unittest import TestCase, TestSuite, main
from datetime import datetime

ce6 = Assembly(assembly_id = 14,
               assembly_name = 'ce6',
               bbcf_valid = True,
               updated_at = datetime.strptime('2010-12-20T07:47:55Z', '%Y-%m-%dT%H:%M:%SZ'),
               nr_assembly_id = 103,
               genome_id = 8,
               source_name = 'UCSC',
               md5 = '75d3de3127a40c1aa5fd835ba35984d40f3405a2',
               source_id = 4,
               created_at = datetime.strptime('2010-12-19T20:52:31Z', '%Y-%m-%dT%H:%M:%SZ'),
               index_path = '/scratch/frt/yearly/genrep/nr_assemblies/bowtie/75d3de3127a40c1aa5fd835ba35984d40f3405a2')
ce6.chromosomes = {(3067, u'NC_003280', 7): {'length': 15279323, 'name': u'chrII'},
                   (3069, u'NC_003282', 5): {'length': 17493785, 'name': u'chrIV'}, 
                   (3068, u'NC_003281', 8): {'length': 13783681, 'name': u'chrIII'}, 
                   (3070, u'NC_003283', 8): {'length': 20919568, 'name': u'chrV'},
                   (3071, u'NC_003284', 7): {'length': 17718854, 'name': u'chrX'}, 
                   (3066, u'NC_003279', 6): {'length': 15072421, 'name': u'chrI'}, 
                   (2948, u'NC_001328', 1): {'length': 13794, 'name': u'chrM'}}


class TestGenRep(TestCase):
    def setUp(self):
        self.genrep = GenRep('http://bbcftools.vital-it.ch/genrep/',
                             '/scratch/frt/yearly/genrep/nr_assemblies/bowtie')
        cp = ConfigParser()
        cp.read('test_data/test.cfg')
        self.genrep_from_config = GenRep(config=cp)

    def test_config_correctly_loaded(self):
        self.assertEqual(self.genrep.url, 'http://bbcftools.vital-it.ch/genrep')
        self.assertEqual(self.genrep.root, '/scratch/frt/yearly/genrep/nr_assemblies/bowtie')

    def test_query_url(self):
        def check_with_url(url):
            g = GenRep(url, '')
            self.assertEqual(g.query_url('boris', 'hilda'),
                             'http://bbcftools.vital-it.ch/genrep/boris.json?assembly_name=hilda')
            self.assertEqual(g.query_url('boris', 36),
                             'http://bbcftools.vital-it.ch/genrep/boris.json?assembly_id=36')
        [check_with_url(u) for u in ['http://bbcftools.vital-it.ch/genrep/',
                                     'http://bbcftools.vital-it.ch/genrep',
                                     'bbcftools.vital-it.ch/genrep/',
                                     'bbcftools.vital-it.ch/genrep']]
        g = GenRep('http://bbcftools.vital-it.ch/genrep', '')
        self.assertRaises(ValueError,
                          lambda : g.query_url('boris',[1,2,3]))

    def assertAssembliesEqual(self, a, b):
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.name, b.name)
        self.assertEqual(a.index_path, b.index_path)
        self.assertEqual(a.bbcf_valid, b.bbcf_valid)
        self.assertEqual(a.updated_at, b.updated_at)
        self.assertEqual(a.nr_assembly_id, b.nr_assembly_id)
        self.assertEqual(a.genome_id, b.genome_id)
        self.assertEqual(a.source_name, b.source_name)
        self.assertEqual(a.md5, b.md5)
        self.assertEqual(a.source_id, b.source_id)
        self.assertEqual(a.created_at, b.created_at)
        self.assertEqual(a.chromosomes, b.chromosomes)        

    def test_assembly_with_name(self):
        a = self.genrep.assembly('ce6')
        self.assertAssembliesEqual(a, ce6)

    def test_assembly_with_id(self):
        a = self.genrep.assembly(14)
        self.assertAssembliesEqual(a, ce6)

    def test_assembly_with_name_from_config(self):
        a = self.genrep_from_config.assembly('ce6')
        self.assertAssembliesEqual(a, ce6)

    def test_assembly_with_id_from_config(self):
        a = self.genrep_from_config.assembly(14)
        self.assertAssembliesEqual(a, ce6)


class TestEmailReport(TestCase):
    def setUp(self):
        self.report = EmailReport(sender='nobody@localhost',
                                  to='ross@localhost',
                                  subject='Default Subject',
                                  smtp_server='localhost')
        cp = ConfigParser()
        cp.read('test_data/test.cfg')
        self.report_from_config = EmailReport(config=cp, to='ross@localhost')

    def test_config_requires_to(self):
        cp = ConfigParser()
        cp.read('test_data/test.cfg')
        self.assertRaises(TypeError,
                          lambda : EmailReport(config=cp))


    def test_init(self):
        self.assertEqual(self.report.sender, 'nobody@localhost')
        self.assertEqual(self.report.to, 'ross@localhost')
        self.assertEqual(self.report.subject, 'Default Subject')
        self.assertEqual(self.report.smtp_server, 'localhost')

    def test_init_from_config(self):
        self.assertEqual(self.report_from_config.sender, 'nobody@localhost')
        self.assertEqual(self.report_from_config.to, 'ross@localhost')
        self.assertEqual(self.report_from_config.subject, 'Default Subject')
        self.assertEqual(self.report_from_config.smtp_server, 'localhost')

    def test_append_body(self):
        a = "This is a test of the emergency broadcasting system."
        self.report.appendBody(a)
        self.assertEqual(self.report.body, a)
        self.report.appendBody(a)
        self.assertEqual(self.report.body, a+a)

    def test_dump(self):
        self.assertEqual(self.report.dump(),
                         {'sender': 'nobody@localhost',
                          'to': 'ross@localhost',
                          'subject': 'Default Subject',
                          'smtp_server': 'localhost',
                          'body': self.report.body})

    def test_send(self):
        self.report.send()


class TestDAFLIMS(TestCase):
    pass

class TestFrontend(TestCase):
    pass

def test_all():
    main()

if __name__ == '__main__':
    test_all()
