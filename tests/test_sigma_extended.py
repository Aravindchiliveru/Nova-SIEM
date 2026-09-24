import unittest
from nova import sigma
from nova.core import Problem

class SigmaExtended(unittest.TestCase):
    def node(self,value,modifier=''):
        return sigma.validate_node(sigma.selection({'Image'+modifier:value},{'Image':'target'}))
    def test_windows_paths_and_escapes(self):
        for pattern,value,expected in [(r'C:\Windows\*.exe',r'C:\Windows*.exe',True),(r'C:\Windows\\*.exe',r'C:\Windows\cmd.exe',True),(r'file\?.txt','file?.txt',True),(r'file?.txt','file1.txt',True),(r'file?.txt','file12.txt',False),(r'C:\Windows\cmd.exe',r'c:\windows\CMD.exe',True)]:
            with self.subTest(pattern=pattern):self.assertEqual(sigma.evaluate(self.node(pattern),{'target':value}),expected)
    def test_contains_wildcard_and_all(self):
        n=self.node(['a*b','c?d'],'|contains|all')
        self.assertTrue(sigma.evaluate(n,{'target':'start axxb cXd end'}));self.assertFalse(sigma.evaluate(n,{'target':'ab cd'}))
    def test_exists_null_empty_distinct(self):
        for event,exists,null,empty in [({},False,True,False),({'target':None},True,True,False),({'target':''},True,False,True)]:
            self.assertEqual(sigma.evaluate(self.node(True,'|exists'),event),exists)
            self.assertEqual(sigma.evaluate(self.node(None),event),null)
            self.assertEqual(sigma.evaluate(self.node(''),event),empty)
    def test_invalid_null_list_exists_type(self):
        for value,modifier in [([None],''),([None,'a'],''),('true','|exists'),(None,'|contains'),(True,'')]:
            with self.subTest(value=value),self.assertRaises(Problem):self.node(value,modifier)
    def test_quantifiers_exclude_private_from_them(self):
        selections={'yes':self.node('a'),'_private':self.node('b')}
        self.assertTrue(sigma.evaluate(sigma.condition('all of them',selections),{'target':'a'}))
        self.assertFalse(sigma.evaluate(sigma.condition('all of *',selections),{'target':'a'}))
        self.assertTrue(sigma.evaluate(sigma.condition('1 of _*',selections),{'target':'b'}))
    def test_conditions_list_and_quantifier_fail_closed(self):
        ss={'one':self.node('a'),'two':self.node('b')}
        self.assertTrue(sigma.evaluate(sigma.condition(['one','two'],ss),{'target':'b'}))
        for text in ['all of absent*','2 of them','1 of','all of them junk']:
            with self.assertRaises(Problem):sigma.condition(text,ss)
    def test_adversarial_glob_and_integer(self):
        self.assertFalse(sigma.wildcard('a'*8192,'*a'*120+'b'))
        self.assertTrue(sigma.evaluate(self.node(42),{'target':'42'}))

    def test_selection_names_are_case_sensitive_and_unicode_values_fold(self):
        self.assertTrue(sigma.evaluate(self.node('İ'),{'target':'i\u0307'}))
        selections={'FooOne':self.node('a'),'fooTwo':self.node('b')}
        self.assertFalse(sigma.evaluate(sigma.condition('1 of Foo*',selections),{'target':'b'}))
