from nacl.signing import SigningKey

keypair = SigningKey.generate()
public_key = keypair.verify_key.encode().hex()
private_key = keypair.encode().hex()

print(f"public key:  {public_key}")   # register this in the webapp
print(f"private key: {private_key}")   # use this to sign API transactions