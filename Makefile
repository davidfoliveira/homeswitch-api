all: packages

PKGFILES = env/ bin/ homeswitch/ scripts/ conf/*sample* requirements.txt README.md Makefile


packages: package-ar71xx

package-ar71xx:
	@tar zcpf packages/homeswitch-ar71xx.tar.gz --exclude 'setuptools*' --exclude 'pip*' --exclude 'distutils*' --exclude 'wheel*' --exclude 'env/lib/python2.7/site-packages/homeswitch*' --exclude 'env/bin' $(PKGFILES)
