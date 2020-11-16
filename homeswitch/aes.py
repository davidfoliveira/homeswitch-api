import pyaes  # https://github.com/ricmoo/pyaes


class AESCipher(object):
    def __init__(self, key):
        self.bs = 16
        self.key = key

    def encrypt(self, raw, use_base64 = True):
        # if Crypto:
        #     raw = self._pad(raw)
        #     cipher = AES.new(self.key, mode=AES.MODE_ECB)
        #     crypted_text = cipher.encrypt(raw)
        # else:
        _ = self._pad(raw)
        cipher = pyaes.blockfeeder.Encrypter(pyaes.AESModeOfOperationECB(self.key))
        crypted_text = cipher.feed(raw)
        crypted_text += cipher.feed()

        if use_base64:
            return base64.b64encode(crypted_text)
        else:
            return crypted_text

    def decrypt(self, enc, use_base64=True):
        if use_base64:
            enc = base64.b64decode(enc)

        # if Crypto:
        #     cipher = AES.new(self.key, AES.MODE_ECB)
        #     raw = cipher.decrypt(enc)
        #     return self._unpad(raw).decode('utf-8')
        # else:
        cipher = pyaes.blockfeeder.Decrypter(pyaes.AESModeOfOperationECB(self.key))
        plain_text = cipher.feed(enc)
        plain_text += cipher.feed()
        return plain_text

    def _pad(self, s):
        padnum = self.bs - len(s) % self.bs
        return s + padnum * chr(padnum).encode()

    @staticmethod
    def _unpad(s):
        return s[:-ord(s[len(s)-1:])]