local mounts = require("shared.mounts")

function love.load(args)
    mounts.mount(args)
    print("server up")
end

function love.update(dt)
end
