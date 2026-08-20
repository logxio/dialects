from dify_plugin import DifyPluginEnv, Plugin

# MAX_REQUEST_TIMEOUT is the ceiling the daemon puts on one invocation. It is a
# plugin-wide setting, not a per-tool one: 60s here covers the tool's own 1-60s
# timeout_seconds with room for the daemon's own round trip.
plugin = Plugin(DifyPluginEnv(MAX_REQUEST_TIMEOUT=60))

if __name__ == "__main__":
    plugin.run()
