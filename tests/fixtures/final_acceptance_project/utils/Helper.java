package utils;

public class Helper {
    public String formatString(String s) {
        return "Java: " + s;
    }

    public static void doJavaWork() {
        Helper helper = new Helper();
        System.out.println(helper.formatString("hello"));
    }
}
