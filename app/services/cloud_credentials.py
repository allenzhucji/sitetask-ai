import keyring
from app.services.local_identity import install_fingerprint

class CloudCredentials:
    SERVICE='SiteTaskAI'
    def token(self):return keyring.get_password(self.SERVICE,'cloud_bridge_token')
    def set_token(self,value):
        import re
        if not re.fullmatch(r'stb_[0-9a-f]{16}_[A-Za-z0-9_-]{43}',value):raise ValueError('invalid_bridge_token')
        keyring.set_password(self.SERVICE,'cloud_bridge_token',value)
    def guard_name(self,path):return 'cloud_bridge_guard:'+install_fingerprint(path)
    def guard(self,path):return keyring.get_password(self.SERVICE,self.guard_name(path))
    def set_guard(self,path):keyring.set_password(self.SERVICE,self.guard_name(path),'paired')
