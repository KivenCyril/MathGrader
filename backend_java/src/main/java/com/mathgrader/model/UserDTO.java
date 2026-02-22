package com.mathgrader.model;

import lombok.Data;

@Data
public class UserDTO {
    private Long id;
    private String username;
    private String role;
    private String password; // Only for create/update
}
