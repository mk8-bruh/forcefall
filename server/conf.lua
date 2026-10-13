function love.conf(t)
    t.identity = "forcefall-server"
    t.version = "12.0"
    t.window = false
    for _, m in ipairs({ "window", "graphics", "audio", "sound", "event", "keyboard", "mouse",
                         "joystick", "touch", "video", "font", "image", "system" }) do
        t.modules[m] = false
    end
end
