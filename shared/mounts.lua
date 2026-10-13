local M = {}

M.points = { ["--core"] = "core", ["--assets"] = "assets" }

local function absolute(path)
    if path:match("^[/\\]") or path:match("^%a:[/\\]") then
        return path
    end
    return love.filesystem.getWorkingDirectory() .. "/" .. path
end

function M.mount(args)
    local mounted = {}
    for i, a in ipairs(args) do
        local point = M.points[a]
        if point and args[i + 1] then
            local dir = absolute(args[i + 1])
            if not love.filesystem.mountFullPath(dir, point, "read", false) then
                error("could not mount " .. point .. " override: " .. dir)
            end
            mounted[point] = dir
            print(point .. " override: " .. dir)
        end
    end
    return mounted
end

return M
