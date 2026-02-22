package com.mathgrader.config;

import com.mathgrader.model.User;
import com.mathgrader.repository.UserRepository;
import org.springframework.boot.CommandLineRunner;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;

@Configuration
public class DataInitializer {

    @Value("${app.default-users.student.username:student}")
    private String studentUsername;

    @Value("${app.default-users.student.password:123456}")
    private String studentPassword;

    @Value("${app.default-users.teacher.username:teacher}")
    private String teacherUsername;

    @Value("${app.default-users.teacher.password:123456}")
    private String teacherPassword;

    @Value("${app.default-users.admin.username:admin}")
    private String adminUsername;

    @Value("${app.default-users.admin.password:admin}")
    private String adminPassword;

    @Bean
    public CommandLineRunner initData(UserRepository userRepository, PasswordEncoder passwordEncoder) {
        return args -> {
            if (userRepository.count() == 0) {
                User student = new User();
                student.setUsername(studentUsername);
                student.setPassword(passwordEncoder.encode(studentPassword));
                student.setRole("ROLE_STUDENT");
                userRepository.save(student);

                User teacher = new User();
                teacher.setUsername(teacherUsername);
                teacher.setPassword(passwordEncoder.encode(teacherPassword));
                teacher.setRole("ROLE_TEACHER");
                userRepository.save(teacher);

                User admin = new User();
                admin.setUsername(adminUsername);
                admin.setPassword(passwordEncoder.encode(adminPassword));
                admin.setRole("ROLE_ADMIN");
                userRepository.save(admin);
                
                System.out.println(
                    "Default users created: " +
                    studentUsername + "/***, " +
                    teacherUsername + "/***, " +
                    adminUsername + "/***"
                );
            }
        };
    }
}
