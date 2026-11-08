// Preview images and downloads.

export function filesRoutes(ctx) {
  const { fail404, fileVersion, model, png, version } = ctx;

  // ------------------------------------------------------------------ files: preview images and downloads
  const fileRoutes = [
    [/^\/bundles\/versions\/(\d+)\/thumbnail$/, (m) => png(version(m[1]).v.thumb)],
    [/^\/source-models\/(\d+)\/versions\/(\d+)\/thumbnail$/, (m) => png(model(m[1]).versions.find((v) => v.version === Number(m[2]))?.thumb)],
    [/^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/preview$/, (m) => png(fileVersion(m[1], m[2], m[3], m[4]).thumb)],
  ];
  const downloadRoutes = [
    [/^\/bundles\/versions\/(\d+)\/download\/(3mf|gcode)$/, (m) => [version(m[1]).v.filename.replace(/\.3mf$/, m[2] === "gcode" ? ".gcode" : ".3mf")]],
    [/^\/source-models\/(\d+)\/versions\/(\d+)\/download$/, (m) => [model(m[1]).name]],
    [/^\/projects\/(\d+)\/(doc|cad|stl|threemf)\/(\d+)\/versions\/(\d+)\/download$/, (m) => [fileVersion(m[1], m[2], m[3], m[4]).filename]],
    [/^\/projects\/(\d+)\/threemf\/(\d+)\/versions\/(\d+)\/gcode$/, (m) => [fileVersion(m[1], "threemf", m[2], m[3]).gcode || fail404("No G-code")]],
  ];
  return { fileRoutes, downloadRoutes };
}
