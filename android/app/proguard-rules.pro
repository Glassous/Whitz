# ==============================================================================
# Whitz Release R8 Optimization & Keep Rules
# ==============================================================================

# 1. Flatten obfuscated package names & shrink source file string pool
-repackageclasses ''
-renamesourcefileattribute SourceFile

# 2. Strip verbose/debug/info Android Log calls in release builds
-assumenosideeffects class android.util.Log {
    public static boolean isLoggable(java.lang.String, int);
    public static int v(...);
    public static int d(...);
    public static int i(...);
}

# 3. kotlinx.serialization + Retrofit converter-kotlinx-serialization (R8 Full Mode safety)
# Keep @Serializable models in Whitz packages (allow obfuscation since JSON keys are
# compile-time constants inside generated $$serializer classes) so Retrofit Type-based
# serializer lookup for @Body, List<T>, and Response<T> never loses metadata or Companion.
-keep,allowobfuscation @kotlinx.serialization.Serializable class com.glassous.whitz.**
-keepclassmembers,allowobfuscation @kotlinx.serialization.Serializable class com.glassous.whitz.** {
    static **$Companion Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclassmembers,allowobfuscation class com.glassous.whitz.**$Companion {
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclassmembers,allowobfuscation class com.glassous.whitz.**$$serializer {
    *;
}

# 4. Coil 3 ServiceLoader targets (coil-network-okhttp does not bundle consumer proguard rules)
-keep class * implements coil3.util.FetcherServiceLoaderTarget {
    public <init>();
}
-keep class * implements coil3.util.DecoderServiceLoaderTarget {
    public <init>();
}
