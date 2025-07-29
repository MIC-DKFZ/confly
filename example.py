from confly import Confly

args = ["model.arch=lol", "model.tmp=1"]
config = Confly(config="tests/configs/interpolation_test", args=args)

print(config)