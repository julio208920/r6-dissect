using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace R6MatchIntelligence.Editor
{
    public static class BuildEntry
    {
        public static void BuildWindows()
        {
            var projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            var scenePath = Path.Combine(projectRoot, "Assets", "Scenes", "CommandCenter.unity");
            var outputPath = Path.Combine(projectRoot, "Builds", "Windows", "R6MatchStats.exe");
            Directory.CreateDirectory(Path.GetDirectoryName(scenePath));
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            EditorSceneManager.SaveScene(scene, scenePath);
            var options = new BuildPlayerOptions
            {
                scenes = new[] { scenePath },
                locationPathName = outputPath,
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None,
            };
            var report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                throw new UnityEditor.Build.BuildFailedException("Unity Windows build failed: " + report.summary.result);
            Debug.Log("R6 Match Stats built at " + outputPath);
        }
    }
}