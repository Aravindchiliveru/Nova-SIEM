import unittest
from nova import sigma
from nova.core import Problem
class ModifierTests(unittest.TestCase):
    def node(self,data):return sigma.validate_node(sigma.selection(data,{'Src':'ip','Dst':'target','User':'actor'}))
    def test_cidr_ipv4_ipv6_and_invalid_events(self):
        n=self.node({'Src|cidr':['10.0.0.0/8','2001:db8::/32']})
        for ip,expected in [('10.255.255.255',True),('11.0.0.1',False),('2001:db8::1',True),('2001:db9::1',False),('hostname',False),('',False)]:
            with self.subTest(ip=ip):self.assertEqual(sigma.evaluate(n,{'ip':ip}),expected)
    def test_invalid_cidr_fails_at_import(self):
        for value in ['bad','10.0.0.0/99','192.0.2.1']:
            with self.assertRaises(Problem):self.node({'Src|cidr':value})
    def test_cased_wildcards(self):
        n=self.node({'Dst|contains|cased':'Ab?'})
        self.assertTrue(sigma.evaluate(n,{'target':'xxAbCxx'}));self.assertFalse(sigma.evaluate(n,{'target':'xxabcxx'}))
    def test_fieldref_is_literal_not_pattern(self):
        n=self.node({'Dst|fieldref':'User'})
        self.assertTrue(sigma.evaluate(n,{'target':'A*','actor':'a*'}));self.assertFalse(sigma.evaluate(n,{'target':'alice','actor':'a*'}));self.assertFalse(sigma.evaluate(n,{'target':'a'}))
    def test_cased_fieldref(self):
        n=self.node({'Dst|fieldref|cased':'User'})
        self.assertFalse(sigma.evaluate(n,{'target':'A','actor':'a'}))
    def test_reject_unmapped_reference_and_invalid_stacks(self):
        for data in [{'Dst|fieldref':'Missing'},{'Src|cidr|cased':'10.0.0.0/8'},{'Dst|all':'a'},{'Dst|all':['a']}]:
            with self.assertRaises(Problem):self.node(data)
    def test_exists_presence_and_legacy_semantics(self):
        n=self.node({'Dst|exists':True});self.assertTrue(sigma.evaluate(n,{'target':None}));self.assertFalse(sigma.evaluate(n,{}))
        old=dict(op='field',field='target',mode='exists',values=[True],all=False)
        self.assertFalse(sigma.evaluate(sigma.validate_node(old),{'target':None}))
